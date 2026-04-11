"""实例会话与实例元数据管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from models.config import AppConfig
from utils.instance_paths import (
    InstancePaths,
    clone_instance,
    create_instance,
    delete_instance,
    list_instances,
    load_profiles_meta,
    rename_instance,
    sanitize_instance_name,
    save_profiles_meta,
)


@dataclass
class InstanceSession:
    """实例会话。"""

    instance_id: str
    name: str
    paths: InstancePaths
    config: AppConfig
    engine: Any = None
    workspace: Any = None
    last_preview: Any = None
    state: str = 'idle'
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec='seconds'))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec='seconds'))

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec='seconds')

    def to_meta(self) -> dict[str, Any]:
        return {
            'id': self.instance_id,
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class InstanceManager:
    """实例管理器。"""

    def __init__(self):
        self._sessions: list[InstanceSession] = []
        self._active_instance_id: str = 'default'

    def load(self) -> None:
        """加载实例元数据与配置。"""
        meta = load_profiles_meta()
        self._sessions.clear()
        for item in list_instances(meta):
            iid = sanitize_instance_name(item.get('id', ''))
            name = str(item.get('name') or iid)
            session = self._build_session(iid, name, item)
            self._sessions.append(session)

        self._active_instance_id = sanitize_instance_name(meta.get('active_instance_id', ''))
        if self._sessions:
            changed = False
            active_cf = self._active_instance_id.casefold()
            matched = next((s.instance_id for s in self._sessions if s.instance_id.casefold() == active_cf), '')
            if matched:
                if self._active_instance_id != matched:
                    changed = True
                self._active_instance_id = matched
            else:
                self._active_instance_id = self._sessions[0].instance_id
                changed = True
            if changed:
                self.save()

    def save(self) -> None:
        """保存实例元数据。"""
        save_profiles_meta(
            {
                'active_instance_id': self._active_instance_id,
                'instances': [session.to_meta() for session in self._sessions],
            }
        )

    def _build_session(self, instance_id: str, name: str, raw: dict[str, Any] | None = None) -> InstanceSession:
        paths = InstancePaths.from_instance_id(instance_id)
        cfg = AppConfig.load(str(paths.config_file))
        raw_data = raw or {}
        return InstanceSession(
            instance_id=instance_id,
            name=name,
            paths=paths,
            config=cfg,
            created_at=str(raw_data.get('created_at') or datetime.now().isoformat(timespec='seconds')),
            updated_at=str(raw_data.get('updated_at') or datetime.now().isoformat(timespec='seconds')),
        )

    def _ensure_unique_id(self, preferred: str) -> str:
        base = sanitize_instance_name(preferred)
        existing = {session.instance_id.casefold() for session in self._sessions}
        if base.casefold() not in existing:
            return base
        for idx in range(2, 10_000):
            candidate = f'{base}{idx}'
            if candidate.casefold() not in existing:
                return candidate
        raise RuntimeError('failed to allocate unique instance id')

    def iter_sessions(self) -> list[InstanceSession]:
        return list(self._sessions)

    def get_session(self, instance_id: str) -> InstanceSession | None:
        iid = sanitize_instance_name(instance_id)
        iid_cf = iid.casefold()
        for session in self._sessions:
            if session.instance_id.casefold() == iid_cf:
                return session
        return None

    def get_active(self) -> InstanceSession | None:
        return self.get_session(self._active_instance_id)

    def switch_active(self, instance_id: str) -> InstanceSession:
        session = self.get_session(instance_id)
        if session is None:
            raise KeyError(f'instance not found: {instance_id}')
        self._active_instance_id = session.instance_id
        self.save()
        return session

    def create_instance(self, name: str) -> InstanceSession:
        target_id = self._ensure_unique_id(name)
        meta = create_instance(target_id, name=name)
        session = self._build_session(meta['id'], str(meta['name']), meta)
        self._sessions.append(session)
        self._active_instance_id = session.instance_id
        self.save()
        return session

    def clone_instance(self, source_instance_id: str, target_name: str) -> InstanceSession:
        source = self.get_session(source_instance_id)
        if source is None:
            raise KeyError(f'instance not found: {source_instance_id}')
        target_id = self._ensure_unique_id(target_name)
        meta = clone_instance(source.instance_id, target_id, target_name=target_name)
        session = self._build_session(meta['id'], str(meta['name']), meta)
        self._sessions.append(session)
        self._active_instance_id = session.instance_id
        self.save()
        return session

    def rename_instance(self, instance_id: str, new_name: str) -> InstanceSession:
        session = self.get_session(instance_id)
        if session is None:
            raise KeyError(f'instance not found: {instance_id}')

        candidate = sanitize_instance_name(new_name)
        if candidate.casefold() == session.instance_id.casefold():
            session.name = str(new_name or session.instance_id)
            session.touch()
            self.save()
            return session

        existing = {
            item.instance_id.casefold()
            for item in self._sessions
            if item.instance_id.casefold() != session.instance_id.casefold()
        }
        new_id = candidate
        if new_id.casefold() in existing:
            for idx in range(2, 10_000):
                alt = f'{candidate}{idx}'
                if alt.casefold() not in existing:
                    new_id = alt
                    break
            else:
                raise RuntimeError('failed to allocate unique instance id')
        meta = rename_instance(session.instance_id, new_id, new_name=new_name)
        session.instance_id = str(meta['id'])
        session.name = str(meta['name'])
        session.paths = InstancePaths.from_instance_id(session.instance_id)
        session.config = AppConfig.load(str(session.paths.config_file))
        session.touch()
        if self._active_instance_id == sanitize_instance_name(instance_id):
            self._active_instance_id = session.instance_id
        self.save()
        return session

    def delete_instance(self, instance_id: str) -> None:
        session = self.get_session(instance_id)
        if session is None:
            raise KeyError(f'instance not found: {instance_id}')
        if len(self._sessions) <= 1:
            raise ValueError('cannot delete last instance')

        self._sessions = [item for item in self._sessions if item.instance_id != session.instance_id]
        delete_instance(session.instance_id)
        if self._active_instance_id == session.instance_id:
            self._active_instance_id = self._sessions[0].instance_id
        self.save()
