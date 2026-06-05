import argparse
import asyncio
import os
import sys
from getpass import getpass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal, engine
from app.models.staff import StaffRole, StaffUser
from app.security.passwords import hash_password
from app.services.otp import InvalidPhoneNumberError, normalize_phone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a staff user.")
    parser.add_argument("--email", required=True, help="Staff email used for admin login.")
    parser.add_argument("--role", choices=[role.value for role in StaffRole], default=StaffRole.admin.value)
    parser.add_argument("--phone", default=None, help="Optional staff phone number.")
    password_group = parser.add_mutually_exclusive_group()
    password_group.add_argument(
        "--password",
        default=None,
        help="Use this password instead of interactive prompt.",
    )
    password_group.add_argument(
        "--password-env",
        default=None,
        help="Read password from this environment variable instead of interactive prompt.",
    )
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="Update password and role if staff user already exists.",
    )
    return parser.parse_args()


def read_password(password: str | None, password_env: str | None) -> str:
    if password:
        return password

    if password_env:
        env_password = os.getenv(password_env)
        if not env_password:
            raise ValueError(f"Environment variable {password_env} is empty or not set.")
        return env_password

    password = getpass("Password: ")
    password_repeat = getpass("Repeat password: ")

    if password != password_repeat:
        raise ValueError("Passwords do not match.")

    return password


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")


def normalize_optional_phone(phone: str | None) -> str | None:
    if not phone:
        return None

    try:
        return normalize_phone(phone)
    except InvalidPhoneNumberError as exc:
        raise ValueError("Invalid phone number.") from exc


async def create_or_update_staff(args: argparse.Namespace) -> int:
    email = args.email.strip().lower()
    password = read_password(args.password, args.password_env)
    validate_password(password)
    phone = normalize_optional_phone(args.phone)
    role = StaffRole(args.role)

    async with AsyncSessionLocal() as db:
        staff = await db.scalar(select(StaffUser).where(StaffUser.email == email))

        if staff and not args.update_password:
            print(f"Staff user already exists: {email}")
            print("Use --update-password if you want to update password and role.")
            return 1

        if staff:
            staff.password_hash = hash_password(password)
            staff.role = role
            staff.is_active = True
            if phone is not None:
                staff.phone = phone
            action = "updated"
        else:
            staff = StaffUser(
                email=email,
                phone=phone,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
            db.add(staff)
            action = "created"

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            print("Could not save staff user. Email or phone is already used.")
            return 1

    print(f"Staff user {action}: {email} ({role.value})")
    return 0


async def async_main() -> int:
    try:
        return await create_or_update_staff(parse_args())
    except ValueError as exc:
        print(str(exc))
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
