"""Seed the LOCAL copy's SQLite DB with test data.

Run:  ./venv/bin/python seed_dev.py
Idempotent — does nothing if users already exist. Only touches the local SQLite
DB (instance/onboarding.db); never connects to prod.
"""
import os

from onboarding_crm import create_app
from onboarding_crm.extensions import db
from onboarding_crm.models import User, OnboardingTemplate, OnboardingInstance
from werkzeug.security import generate_password_hash


def _blocks(n):
    return [{
        "type": "stage",
        "title": f"Блок {i}. Тема етапу {i}",
        "description": f"<p>Опис етапу {i}</p>",
        "subblocks": [],
        "test": {"questions": []},
        "open_questions": [],
    } for i in range(1, n + 1)]


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        if User.query.first():
            print("Данные уже есть — пропускаю сидинг.")
            return

        def mk(role, username, password, dept="product", added_by=None, pos=None):
            u = User(
                username=username,
                password=generate_password_hash(password),
                role=role, department=dept, added_by_id=added_by,
                tg_nick="@" + username, position=pos, is_active=True,
            )
            db.session.add(u); db.session.commit()
            return u.id

        dev = mk("developer", "dev", "dev123", dept=None)
        mk("admin", "admin_t", "admin123", dept=None)  # template-steward admin
        tl = mk("teamlead", "tl", "tl123")
        mentor = mk("mentor", "mentor", "mentor123", added_by=tl)
        m1 = mk("manager", "olena", "olena123", added_by=mentor, pos="Sales")
        m2 = mk("manager", "ivan", "ivan123", added_by=mentor, pos="Support")

        # New model: ONE master per department, all blocks (each with a stable id).
        from onboarding_crm.services.master import ensure_block_ids
        master = OnboardingTemplate(
            name="Майстер онбордингу — product",
            structure=ensure_block_ids({"blocks": _blocks(8)}),
            created_by=mentor, department="product", is_master=True,
        )
        db.session.add(master)

        # Second department (to test "send to department") + its people.
        mk("teamlead", "tl_buying", "tl123", dept="buying")
        mk("manager", "petro", "petro123", dept="buying")

        # Devops library pool (is_library) — raw material for the constructor; no department.
        # department='' (not None): the column's scalar default 'product' fires on None, so an
        # empty string is how a library template stays department-less (shows as «—»).
        for nm, n in [("Компанія 101", 4), ("Безпека та доступи", 3), ("Продукт: базовий", 5)]:
            db.session.add(OnboardingTemplate(
                name=nm, structure=ensure_block_ids({"blocks": _blocks(n)}),
                created_by=dev, department='', is_library=True))
        db.session.commit()

        # Sample assignment: olena gets a subset of master blocks (1, 3, 5) — new model.
        mblocks = master.structure["blocks"]
        chosen = [mblocks[i]["id"] for i in (0, 2, 4)]
        db.session.add(OnboardingInstance(
            name="Онбординг для @olena", manager_id=m1, mentor_id=mentor,
            master_template_id=master.id, selected_block_ids=chosen,
            structure={"blocks": [b for b in mblocks if b["id"] in chosen]},
            onboarding_step=0))
        db.session.commit()

        print("Готово. Тестовые логины (пароль):")
        print("  dev / dev123          (developer)")
        print("  admin_t / admin123    (admin — шаблони)")
        print("  tl / tl123            (teamlead)")
        print("  mentor / mentor123    (mentor — редактирует шаблоны)")
        print("  olena / olena123      (manager)")
        print("  ivan / ivan123        (manager)")


if __name__ == "__main__":
    main()
