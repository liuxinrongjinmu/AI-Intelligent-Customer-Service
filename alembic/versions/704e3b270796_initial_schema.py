"""initial_schema

Revision ID: 704e3b270796
Revises:
Create Date: 2026-06-24 17:39:41.353918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '704e3b270796'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建所有业务表（首次迁移，与 ORM 模型完全一致）"""

    # ─── 租户表 ──────────────────────────────────────────────
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('api_key_hash', sa.String(length=256), nullable=False),
        sa.Column('api_key_prefix', sa.String(length=16), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id'),
        sa.UniqueConstraint('api_key_hash'),
    )

    # ─── 会话表 ──────────────────────────────────────────────
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('thread_id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('user_name', sa.String(length=128), nullable=True),
        sa.Column('channel', sa.String(length=16), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True, server_default="'ai_serving'"),
        sa.Column('agent_id', sa.String(length=64), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('context_snapshot', sa.JSON(), nullable=True),
        sa.Column('ai_failed_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('message_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('rating', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('thread_id'),
    )
    op.create_index('ix_conversations_created_at', 'conversations', ['created_at'])
    op.create_index('ix_conversations_ended_at', 'conversations', ['ended_at'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_index('ix_conversations_tenant_id', 'conversations', ['tenant_id'])
    op.create_index('ix_conversations_status', 'conversations', ['status'])

    # ─── 消息表 ──────────────────────────────────────────────
    op.create_table(
        'messages',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('conversation_id', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('intent', sa.String(length=32), nullable=True),
        sa.Column('intent_sub_type', sa.String(length=32), nullable=True),
        sa.Column('entities', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])

    # ─── 工具调用日志表 ──────────────────────────────────────
    op.create_table(
        'tool_call_logs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('conversation_id', sa.String(length=64), nullable=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('tool_name', sa.String(length=64), nullable=False),
        sa.Column('tool_params', sa.JSON(), nullable=True),
        sa.Column('tool_result', sa.JSON(), nullable=True),
        sa.Column('success', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tool_call_logs_conversation_id', 'tool_call_logs', ['conversation_id'])
    op.create_index('ix_tool_call_logs_tenant_id', 'tool_call_logs', ['tenant_id'])

    # ─── FAQ 知识库表 ────────────────────────────────────────
    op.create_table(
        'faqs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=True, server_default="'通用'"),
        sa.Column('tags', sa.String(length=256), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('chroma_ids', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_faqs_tenant_id', 'faqs', ['tenant_id'])

    # ─── 文档知识库表 ────────────────────────────────────────
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=256), nullable=False),
        sa.Column('file_type', sa.String(length=16), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('chunk_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('chroma_ids', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_documents_tenant_id', 'documents', ['tenant_id'])

    # ─── 转人工工单表 ────────────────────────────────────────
    op.create_table(
        'handoff_tickets',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('conversation_id', sa.String(length=64), nullable=False),
        sa.Column('thread_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=True),
        sa.Column('user_name', sa.String(length=128), nullable=True),
        sa.Column('reason', sa.String(length=32), nullable=False),
        sa.Column('reason_detail', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True, server_default="'pending'"),
        sa.Column('priority', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('assigned_to', sa.String(length=128), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_handoff_tickets_tenant_id', 'handoff_tickets', ['tenant_id'])
    op.create_index('ix_handoff_tickets_status', 'handoff_tickets', ['status'])
    op.create_index('ix_handoff_tickets_created_at', 'handoff_tickets', ['created_at'])
    op.create_index('idx_handoff_tenant_status', 'handoff_tickets', ['tenant_id', 'status'])

    # ─── 知识库同步日志表 ────────────────────────────────────
    op.create_table(
        'sync_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('kb_type', sa.String(length=32), nullable=False),
        sa.Column('sync_type', sa.String(length=32), nullable=False),
        sa.Column('item_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('processed_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('deleted_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('snapshot', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True, server_default="'success'"),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_logs_tenant_id', 'sync_logs', ['tenant_id'])

    # ─── 用户反馈表 ──────────────────────────────────────────
    op.create_table(
        'feedbacks',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('conversation_id', sa.String(length=64), nullable=False),
        sa.Column('thread_id', sa.String(length=64), nullable=False),
        sa.Column('message_id', sa.String(length=64), nullable=True, server_default=sa.text("''")),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True, server_default=sa.text("''")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedbacks_tenant_id', 'feedbacks', ['tenant_id'])
    op.create_index('ix_feedbacks_conversation_id', 'feedbacks', ['conversation_id'])
    op.create_index('ix_feedbacks_created_at', 'feedbacks', ['created_at'])


def downgrade() -> None:
    """回滚所有表"""
    op.drop_table('feedbacks')
    op.drop_table('sync_logs')
    op.drop_table('handoff_tickets')
    op.drop_table('documents')
    op.drop_table('faqs')
    op.drop_table('tool_call_logs')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('tenants')
