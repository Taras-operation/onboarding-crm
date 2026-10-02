"""Master-template-per-department model: Кошик (soft delete), devops library, live
manager block subsets — schema + data backfill.

Prod reached its current shape partly via create_all (the onboarding_instance table
is missing columns that models.py already declares: test_progress, onboarding_status,
final_decision, final_comment, archived). So every column add here is IDEMPOTENT — it
is applied only when the column is absent. That makes this migration correct whether a
given database followed the strict migration chain or was create_all'd + stamped.

Data backfill:
  * every block in every template/instance structure gets a stable `id`
    (the new model references blocks by id, not list position);
  * each active instance's test_progress is remapped from the OLD step-INDEX keys
    ("0","1",…, position among stage blocks) to the NEW stable block-id keys, so a
    manager's completed steps are preserved.

Revision ID: f4b1c2d3e5a6
Revises: c8d4e2f10a9b
Create Date: 2026-10-02
"""
import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f4b1c2d3e5a6'
down_revision = 'c8d4e2f10a9b'
branch_labels = None
depends_on = None

# JSONB on Postgres, plain JSON elsewhere — mirrors models.JSON_TYPE.
_JSONB = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')

# (table, Column) — added only if the column is not already present.
_COLUMNS = [
    ('user', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false'))),
    ('user', sa.Column('archived_at', sa.DateTime(), nullable=True)),

    ('onboarding_template', sa.Column('is_master', sa.Boolean(), nullable=False, server_default=sa.text('false'))),
    ('onboarding_template', sa.Column('is_library', sa.Boolean(), nullable=False, server_default=sa.text('false'))),
    ('onboarding_template', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false'))),
    ('onboarding_template', sa.Column('archived_at', sa.DateTime(), nullable=True)),

    # master_template_id is added separately (it needs a FK) — see upgrade().
    ('onboarding_instance', sa.Column('selected_block_ids', sa.JSON(), nullable=True)),
    ('onboarding_instance', sa.Column('locked_blocks', _JSONB, nullable=True)),
    # These five already exist on prod (create_all). Added defensively for any DB that
    # strictly followed migrations and therefore lacks them.
    ('onboarding_instance', sa.Column('test_progress', _JSONB, nullable=True)),
    ('onboarding_instance', sa.Column('onboarding_status', sa.String(length=50), nullable=True)),
    ('onboarding_instance', sa.Column('final_decision', sa.String(length=50), nullable=True)),
    ('onboarding_instance', sa.Column('final_comment', sa.Text(), nullable=True)),
    ('onboarding_instance', sa.Column('archived', sa.Boolean(), nullable=True, server_default=sa.text('false'))),
]

# (index_name, table, column) — SQLAlchemy's default ix_<table>_<col> names.
_INDEXES = [
    ('ix_user_is_archived', 'user', 'is_archived'),
    ('ix_onboarding_template_is_master', 'onboarding_template', 'is_master'),
    ('ix_onboarding_template_is_library', 'onboarding_template', 'is_library'),
    ('ix_onboarding_template_is_archived', 'onboarding_template', 'is_archived'),
]

# Columns this migration is solely responsible for (dropped on downgrade). The five
# create_all-drift columns are intentionally NOT dropped — they predate this migration.
_OWNED_COLUMNS = [
    ('user', 'is_archived'), ('user', 'archived_at'),
    ('onboarding_template', 'is_master'), ('onboarding_template', 'is_library'),
    ('onboarding_template', 'is_archived'), ('onboarding_template', 'archived_at'),
    ('onboarding_instance', 'master_template_id'),
    ('onboarding_instance', 'selected_block_ids'), ('onboarding_instance', 'locked_blocks'),
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _cols(insp, table):
    return {c['name'] for c in insp.get_columns(table)}


def _indexes(insp, table):
    return {i['name'] for i in insp.get_indexes(table)}


def _normalize(structure):
    """Return (parsed_structure, blocks_list). Handles dict, list, JSON string, None."""
    if isinstance(structure, str):
        try:
            structure = json.loads(structure)
        except Exception:
            return None, []
    if isinstance(structure, dict):
        blocks = structure.get('blocks')
    elif isinstance(structure, list):
        blocks = structure
    else:
        return structure, []
    return structure, (blocks if isinstance(blocks, list) else [])


def _ensure_ids(blocks):
    """Give every block a stable id (preserving order). Returns True if anything changed."""
    seen, changed = set(), False
    for b in blocks:
        if not isinstance(b, dict):
            continue
        bid = b.get('id')
        if not bid or bid in seen:
            bid = uuid.uuid4().hex[:12]
            b['id'] = bid
            changed = True
        seen.add(bid)
    return changed


def _as_dict(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


# ── upgrade ──────────────────────────────────────────────────────────────────

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == 'postgresql'

    # 1) additive columns (idempotent)
    for table, col in _COLUMNS:
        if col.name not in _cols(insp, table):
            op.add_column(table, col)

    # 2) master_template_id (+ FK ON DELETE SET NULL)
    if 'master_template_id' not in _cols(insp, 'onboarding_instance'):
        op.add_column('onboarding_instance', sa.Column('master_template_id', sa.Integer(), nullable=True))
        if is_pg:  # SQLite can't add a FK post-hoc without a table rebuild; it also
                   # doesn't enforce FKs by default — skip there (dev only).
            op.create_foreign_key(
                'fk_onboarding_instance_master_template_id',
                'onboarding_instance', 'onboarding_template',
                ['master_template_id'], ['id'], ondelete='SET NULL',
            )

    # 3) indexes (idempotent)
    insp = sa.inspect(bind)  # refresh after column adds
    for name, table, column in _INDEXES:
        if name not in _indexes(insp, table):
            op.create_index(name, table, [column])

    # 4) data backfill — block ids in every template & instance structure
    _backfill_template_block_ids(bind)
    _backfill_instance_structure_and_progress(bind)


def _json_param(dialect_is_pg):
    """A bindparam that serializes dict/list to JSON text for the UPDATE."""
    return sa.bindparam('val', type_=sa.JSON())


def _update_json(bind, table, column, row_id, value):
    bind.execute(
        sa.text(f"UPDATE {table} SET {column} = :val WHERE id = :id").bindparams(
            sa.bindparam('val', value=value, type_=sa.JSON()),
            sa.bindparam('id', value=row_id),
        )
    )


def _backfill_template_block_ids(bind):
    rows = bind.execute(sa.text("SELECT id, structure FROM onboarding_template")).fetchall()
    for row_id, structure in rows:
        parsed, blocks = _normalize(structure)
        if not blocks:
            continue
        if _ensure_ids(blocks):
            if isinstance(parsed, dict):
                parsed['blocks'] = blocks
                new_struct = parsed
            else:
                new_struct = {'blocks': blocks}
            _update_json(bind, 'onboarding_template', 'structure', row_id, new_struct)


def _backfill_instance_structure_and_progress(bind):
    rows = bind.execute(
        sa.text("SELECT id, structure, test_progress FROM onboarding_instance")
    ).fetchall()
    for row_id, structure, progress in rows:
        parsed, blocks = _normalize(structure)
        changed = _ensure_ids(blocks) if blocks else False

        # Remap test_progress: old keys are "0","1",… = index into STAGE blocks.
        prog = _as_dict(progress)
        new_prog, remapped = prog, False
        if prog and blocks:
            stage_blocks = [b for b in blocks if isinstance(b, dict) and b.get('type') == 'stage']
            new_prog = {}
            for key, val in prog.items():
                if isinstance(key, str) and key.isdigit():
                    i = int(key)
                    if 0 <= i < len(stage_blocks):
                        new_prog[stage_blocks[i]['id']] = val
                    # else: orphan index (block removed) → drop it
                    remapped = True
                else:
                    new_prog[key] = val  # already id-keyed → keep as-is

        if changed:
            if isinstance(parsed, dict):
                parsed['blocks'] = blocks
                new_struct = parsed
            else:
                new_struct = {'blocks': blocks}
            _update_json(bind, 'onboarding_instance', 'structure', row_id, new_struct)
        if remapped:
            _update_json(bind, 'onboarding_instance', 'test_progress', row_id, new_prog)


# ── downgrade ────────────────────────────────────────────────────────────────

def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == 'postgresql'

    for name, table, _ in _INDEXES:
        if name in _indexes(insp, table):
            op.drop_index(name, table_name=table)

    if is_pg and 'master_template_id' in _cols(insp, 'onboarding_instance'):
        try:
            op.drop_constraint('fk_onboarding_instance_master_template_id',
                               'onboarding_instance', type_='foreignkey')
        except Exception:
            pass

    for table, col in _OWNED_COLUMNS:
        if col in _cols(insp, table):
            op.drop_column(table, col)
