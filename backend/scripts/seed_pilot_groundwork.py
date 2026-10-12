"""Milestone M4C Phase 1: Seed Pilot Groundwork & Calibration entities.

Creates:
1. Designated single pilot project (PRJ-DXB-01).
2. Two participating primary suppliers (Ready-mix concrete & Steel rebar).
3. Four named pilot users with distinct credentials and roles:
   - Storekeeper (ENGINEER, can_review=False)
   - Site Engineer (ENGINEER, can_review=False)
   - Project QS (QS, can_review=False)
   - Commercial Director / PM (REVIEWER, can_review=True)
4. Project user assignments linking all 4 users to the pilot project.

Zero real commercial documents are touched or created.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.security import hash_password
from app.persistence.database import SessionLocal
from app.persistence.models import ProjectOrm, ProjectUserOrm, SupplierOrm, UserOrm


PILOT_PROJECT = {
    "id": "prj-pilot-dxb-01",
    "code": "PRJ-DXB-01",
    "name": "Crown Horizon Residences - Tower A",
    "client": "Horizon Capital Developments PJSC (Synthetic)",
    "site_location": "Business District Plot 345-1200",
    "active": True,
}

PILOT_SUPPLIERS = [
    {
        "id": "sup-pilot-rmc-01",
        "name": "Apex Ready Mix Concrete LLC (Synthetic)",
        "trn": "100234567800003",
        "aliases": ["Apex Concrete", "Apex RMC"],
        "active": True,
    },
    {
        "id": "sup-pilot-steel-02",
        "name": "Gulf Rebar Steel Industries LLC (Synthetic)",
        "trn": "100345678900003",
        "aliases": ["Gulf Rebar", "GRSI Steel"],
        "active": True,
    },
]

# Pilot credentials are provisioned locally via environment variables.
# Never commit plaintext passwords to source control.
PILOT_USERS = [
    {
        "id": "usr-pilot-storekeeper",
        "name": "Tariq Mansoor (Storekeeper)",
        "email": "tariq.store@pilot.civ.local",
        "env_var": "PILOT_STOREKEEPER_PASSWORD",
        "role": "ENGINEER",
        "can_review": False,
        "active": True,
    },
    {
        "id": "usr-pilot-site-eng",
        "name": "Ahmed Al-Hashimi (Site Engineer)",
        "email": "ahmed.eng@pilot.civ.local",
        "env_var": "PILOT_SITE_ENG_PASSWORD",
        "role": "ENGINEER",
        "can_review": False,
        "active": True,
    },
    {
        "id": "usr-pilot-project-qs",
        "name": "Ramesh (Project QS)",
        "email": "ramesh.qs@pilot.civ.local",
        "env_var": "PILOT_PROJECT_QS_PASSWORD",
        "role": "QS",
        "can_review": False,
        "active": True,
    },
    {
        "id": "usr-pilot-pm-reviewer",
        "name": "David Sterling (Commercial Director / PM)",
        "email": "david.pm@pilot.civ.local",
        "env_var": "PILOT_PM_REVIEWER_PASSWORD",
        "role": "REVIEWER",
        "can_review": True,
        "active": True,
    },
]


def seed_pilot_groundwork() -> dict[str, int]:
    db = SessionLocal()
    counts = {"projects": 0, "suppliers": 0, "users": 0, "assignments": 0}

    try:
        # 1. Pilot Project
        project = db.query(ProjectOrm).filter(ProjectOrm.id == PILOT_PROJECT["id"]).first()
        if not project:
            project = ProjectOrm(**PILOT_PROJECT)
            db.add(project)
            counts["projects"] += 1
            print(f"Created Pilot Project: {project.code} - {project.name}")
        else:
            print(f"Pilot Project already exists: {project.code}")

        # 2. Pilot Suppliers
        for sup_data in PILOT_SUPPLIERS:
            supplier = db.query(SupplierOrm).filter(SupplierOrm.id == sup_data["id"]).first()
            if not supplier:
                supplier = SupplierOrm(**sup_data)
                db.add(supplier)
                counts["suppliers"] += 1
                print(f"Created Pilot Supplier: {supplier.name} (TRN: {supplier.trn})")
            else:
                print(f"Pilot Supplier already exists: {supplier.name}")

        # 3. Pilot Users
        for user_data in PILOT_USERS:
            user = db.query(UserOrm).filter(UserOrm.id == user_data["id"]).first()
            env_var_name = user_data["env_var"]
            raw_password = os.environ.get(env_var_name)

            if not user:
                if not raw_password:
                    raise ValueError(
                        f"Pilot user {user_data['email']} requires password provisioned via environment variable {env_var_name}."
                    )
                hashed_pwd = hash_password(raw_password)
                user = UserOrm(
                    id=user_data["id"],
                    name=user_data["name"],
                    email=user_data["email"],
                    hashed_password=hashed_pwd,
                    role=user_data["role"],
                    can_review=user_data["can_review"],
                    active=user_data["active"],
                )
                db.add(user)
                counts["users"] += 1
                print(f"Created Pilot User: {user.name} ({user.email}) [Role: {user.role}, can_review: {user.can_review}]")
            else:
                if raw_password:
                    user.hashed_password = hash_password(raw_password)
                user.role = user_data["role"]
                user.can_review = user_data["can_review"]
                print(f"Pilot User verified: {user.name} ({user.email})")

        db.commit()

        # 4. Project Assignments
        for user_data in PILOT_USERS:
            existing_assignment = (
                db.query(ProjectUserOrm)
                .filter(
                    ProjectUserOrm.project_id == PILOT_PROJECT["id"],
                    ProjectUserOrm.user_id == user_data["id"],
                )
                .first()
            )
            if not existing_assignment:
                assignment = ProjectUserOrm(
                    project_id=PILOT_PROJECT["id"],
                    user_id=user_data["id"],
                    assigned_by=PILOT_USERS[3]["id"],  # Assigned by PM
                )
                db.add(assignment)
                counts["assignments"] += 1
                print(f"Assigned User {user_data['name']} to Project {PILOT_PROJECT['code']}")
            else:
                print(f"User {user_data['name']} already assigned to Project {PILOT_PROJECT['code']}")

        db.commit()
        print("\nPilot groundwork seeding completed successfully.")
        return counts

    except Exception as exc:
        db.rollback()
        print(f"Error during pilot groundwork seeding: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_pilot_groundwork()
