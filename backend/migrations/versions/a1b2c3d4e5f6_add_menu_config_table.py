"""add_menu_config_table

Revision ID: a1b2c3d4e5f6
Revises: f7a6d3e5b204
Create Date: 2026-06-29

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f7a6d3e5b204'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sys_menu_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='配置ID'),
        sa.Column('menu_code', sa.String(length=80), nullable=False, comment='菜单编码'),
        sa.Column('menu_name', sa.String(length=120), nullable=False, comment='菜单显示名称'),
        sa.Column('identity_type', sa.String(length=20), nullable=False, comment='身份类型：PLATFORM/CUSTOMER'),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序权重'),
        sa.Column('is_visible', sa.Boolean(), server_default='1', nullable=False, comment='是否可见'),
        sa.Column('icon', sa.String(length=50), nullable=True, comment='图标名称'),
        sa.Column('route_path', sa.String(length=255), nullable=True, comment='路由路径'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注说明'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted', sa.Boolean(), server_default='0', nullable=False, comment='逻辑删除'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sys_menu_config_deleted'), 'sys_menu_config', ['deleted'], unique=False)
    op.create_index(op.f('ix_sys_menu_config_identity_type'), 'sys_menu_config', ['identity_type'], unique=False)
    op.create_index(op.f('ix_sys_menu_config_is_visible'), 'sys_menu_config', ['is_visible'], unique=False)
    op.create_index(op.f('ix_sys_menu_config_menu_code'), 'sys_menu_config', ['menu_code'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_sys_menu_config_menu_code'), table_name='sys_menu_config')
    op.drop_index(op.f('ix_sys_menu_config_is_visible'), table_name='sys_menu_config')
    op.drop_index(op.f('ix_sys_menu_config_identity_type'), table_name='sys_menu_config')
    op.drop_index(op.f('ix_sys_menu_config_deleted'), table_name='sys_menu_config')
    op.drop_table('sys_menu_config')
