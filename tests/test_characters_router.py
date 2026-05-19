from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import CurrentUserInfo, get_current_user
from server.routers import characters


class _FakePM:
    def __init__(self):
        self.projects = {
            "demo": {
                "characters": {
                    "Alice": {
                        "description": "old",
                        "voice_style": "soft",
                        "character_sheet": "",
                        "reference_image": "",
                    }
                }
            }
        }

    def _add_asset(self, asset_type, project_name, name, entry):
        if project_name not in self.projects:
            raise FileNotFoundError(project_name)
        bucket = self.projects[project_name].setdefault("characters", {})
        if name in bucket:
            return False
        bucket[name] = entry
        return True

    def load_project(self, project_name):
        if project_name not in self.projects:
            raise FileNotFoundError(project_name)
        return self.projects[project_name]

    def save_project(self, project_name, project):
        self.projects[project_name] = project

    def update_project(self, project_name, mutate_fn):
        project = self.load_project(project_name)
        mutate_fn(project)
        self.save_project(project_name, project)

    def get_project_path(self, project_name):
        if project_name not in self.projects:
            raise FileNotFoundError(project_name)
        return Path("/tmp") / project_name

    def remove_character_input_ref(self, project_name, char_name, form_id, ref_path):
        project = self.load_project(project_name)
        refs = project["characters"][char_name]["forms"][form_id]["input_refs"]
        if ref_path in refs:
            refs.remove(ref_path)
        return project


def _client(monkeypatch, fake_pm):
    monkeypatch.setattr(characters, "get_project_manager", lambda: fake_pm)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(characters.router, prefix="/api/v1")
    return TestClient(app)


class TestCharactersRouter:
    def test_add_update_delete_character(self, monkeypatch):
        fake_pm = _FakePM()
        with _client(monkeypatch, fake_pm) as client:
            add_resp = client.post(
                "/api/v1/projects/demo/characters",
                json={"name": "Bob", "description": "new char", "voice_style": "calm"},
            )
            assert add_resp.status_code == 200
            assert add_resp.json()["character"]["description"] == "new char"

            patch_resp = client.patch(
                "/api/v1/projects/demo/characters/Alice",
                json={
                    "description": "updated",
                    "voice_style": "strong",
                    "character_sheet": "characters/Alice.png",
                    "reference_image": "characters/refs/Alice.png",
                },
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["character"]["description"] == "updated"

            delete_resp = client.delete("/api/v1/projects/demo/characters/Bob")
            assert delete_resp.status_code == 200
            assert "已删除" in delete_resp.json()["message"]

    def test_error_mapping(self, monkeypatch):
        fake_pm = _FakePM()
        with _client(monkeypatch, fake_pm) as client:
            not_found = client.post(
                "/api/v1/projects/missing/characters",
                json={"name": "Bob", "description": "x", "voice_style": "y"},
            )
            assert not_found.status_code == 404

            missing_char = client.patch(
                "/api/v1/projects/demo/characters/Nope",
                json={"description": "x"},
            )
            assert missing_char.status_code == 404

            missing_delete = client.delete("/api/v1/projects/demo/characters/Nope")
            assert missing_delete.status_code == 404

    def test_delete_character_input_ref_updates_project_json(self, monkeypatch):
        fake_pm = _FakePM()
        fake_pm.projects["demo"]["characters"]["Alice"] = {
            "description": "old",
            "voice_style": "soft",
            "default_form": "default",
            "forms": {
                "default": {
                    "label": "默认造型",
                    "description": "old",
                    "storyboard_ref_slot": "full_body",
                    "input_refs": ["characters/Alice/default/input_refs/style.png"],
                    "refs": {
                        "full_body": {"path": "", "purpose": "storyboard_reference"},
                        "three_view": {"path": "", "purpose": "consistency_review"},
                    },
                }
            },
        }

        with _client(monkeypatch, fake_pm) as client:
            resp = client.request(
                "DELETE",
                "/api/v1/projects/demo/characters/Alice/forms/default/input-refs",
                json={"path": "characters/Alice/default/input_refs/style.png"},
            )

            assert resp.status_code == 200
            assert fake_pm.projects["demo"]["characters"]["Alice"]["forms"]["default"]["input_refs"] == []
