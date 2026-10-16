import io

from campus import db

from .conftest import ROOT, make_user, needs_search, sign_in


# --- First-time setup and sign-in --------------------------------------------------------

def test_fresh_install_goes_to_setup(client):
    assert client.get("/").headers["Location"] == "/setup"
    assert client.get("/api/status").json["setup_needed"] is True


def test_setup_creates_first_admin_only_once(client):
    res = client.post("/api/setup", json={"login": "Admin1", "name": "Admin", "password": "secret123"})
    assert res.status_code == 200
    assert client.get("/api/me").json["may_enroll"] is True  # may register own face next
    again = client.post("/api/setup", json={"login": "evil", "name": "Evil", "password": "secret123"})
    assert again.status_code == 409
    assert [u["login"] for u in db.list_users()] == ["Admin1"]
    assert client.get("/setup").status_code == 302


def test_setup_validates_password(client):
    res = client.post("/api/setup", json={"login": "a", "name": "A", "password": "123"})
    assert res.status_code == 422


def test_login_then_face_check_required(client):
    make_user()
    bad = client.post("/api/login", json={"login": "student1", "password": "wrong"})
    assert bad.status_code == 401 and bad.json["error"] == "Wrong ID or password."
    unknown = client.post("/api/login", json={"login": "nobody", "password": "wrong"})
    assert unknown.json["error"] == bad.json["error"]  # doesn't reveal which IDs exist

    ok = client.post("/api/login", json={"login": "STUDENT1", "password": "secret123"})  # ID is case-insensitive
    assert ok.status_code == 200
    assert client.get("/").headers["Location"] == "/face"
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 403
    me = client.get("/api/me").json
    assert me["face_enrolled"] is False and me["may_enroll"] is False


def test_login_lockout(client):
    make_user()
    for _ in range(5):
        client.post("/api/login", json={"login": "student1", "password": "wrong"})
    res = client.post("/api/login", json={"login": "student1", "password": "secret123"})
    assert res.status_code == 429


def test_signed_out_user_sees_login_page(client):
    make_user()
    res = client.get("/")
    assert res.status_code == 200 and b"Sign in" in res.data


def test_only_first_admin_may_self_enroll(client):
    user = make_user()
    sign_in(client, user, face_ok=False)
    res = client.post("/api/face/enroll", data=b"x", headers={"X-Width": "1", "X-Height": "1"})
    assert res.status_code == 403


def test_face_verify_needs_registered_face(client):
    user = make_user()
    sign_in(client, user, face_ok=False)
    res = client.post("/api/face/verify", data=b"x", headers={"X-Width": "64", "X-Height": "64"})
    assert res.status_code == 404


# --- Permissions ----------------------------------------------------------------------------

def test_api_needs_sign_in(client):
    make_user()
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401
    assert client.post("/api/transcribe", data=b"").status_code == 401
    assert client.get("/api/admin/modules").status_code == 401


def test_admin_api_is_admin_only(client):
    sign_in(client, make_user())
    assert client.get("/api/admin/modules").status_code == 403
    assert client.get("/admin").status_code == 302
    sign_in(client, make_user("boss", "admin"))
    assert client.get("/api/admin/modules").status_code == 200
    assert client.get("/admin").status_code == 200


def test_admin_still_needs_face_check(client):
    sign_in(client, make_user("boss", "admin"), face_ok=False)
    assert client.get("/api/admin/users").status_code == 403


def test_cross_site_posts_are_blocked(client):
    sign_in(client, make_user("boss", "admin"))
    res = client.post("/api/admin/modules", json={"title": "t", "content": "c"}, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403


def test_deleted_user_is_signed_out(client):
    user = make_user()
    sign_in(client, user)
    db.delete_user(user["id"])
    assert client.get("/api/me").status_code == 401


# --- Admin: users -------------------------------------------------------------------------

def test_user_management(client):
    admin = make_user("boss", "admin")
    sign_in(client, admin)
    res = client.post("/api/admin/users", json={"login": "4nm23is001", "name": "Asha", "role": "student", "password": "pass1234"})
    assert res.status_code == 201
    new_id = res.json["id"]
    assert client.post("/api/admin/users", json={"login": "4NM23IS001", "name": "Dup", "role": "student", "password": "pass1234"}).status_code == 409
    assert client.post("/api/admin/users", json={"login": "x", "name": "X", "role": "pmo", "password": "pass1234"}).status_code == 422

    res = client.put(f"/api/admin/users/{new_id}", json={"name": "Asha K", "role": "student", "password": "newpass1"})
    assert res.json["name"] == "Asha K"
    client.get("/logout")
    assert client.post("/api/login", json={"login": "4nm23is001", "password": "newpass1"}).status_code == 200

    sign_in(client, admin)
    assert client.delete(f"/api/admin/users/{admin['id']}").status_code == 409          # not yourself
    assert client.put(f"/api/admin/users/{admin['id']}", json={"name": "B", "role": "student"}).status_code == 409  # last admin
    assert client.delete(f"/api/admin/users/{new_id}").status_code == 204
    assert [u["login"] for u in client.get("/api/admin/users").json] == ["boss"]


def test_users_list_never_exposes_password_or_face(client):
    sign_in(client, make_user("boss", "admin"))
    user = client.get("/api/admin/users").json[0]
    assert "password_hash" not in user and "face" not in user and user["has_face"] == 0


# --- Admin: knowledge and answers -----------------------------------------------------------

@needs_search
def test_knowledge_crud_and_answers_follow_edits(client):
    sign_in(client, make_user("boss", "admin"))
    created = client.post("/api/admin/modules", json={"title": "Library timings", "content": "The library opens at 8:30 AM."}).json
    answer = client.post("/api/ask", json={"question": "When does the library open?"}).json
    assert "8:30" in answer["answer"] and answer["sources"] == ["Library timings"]

    client.put(f"/api/admin/modules/{created['id']}", json={"title": "Library timings", "content": "The library opens at 9 AM."})
    assert "9 AM" in client.post("/api/ask", json={"question": "When does the library open?"}).json["answer"]

    assert client.delete(f"/api/admin/modules/{created['id']}").status_code == 204
    gone = client.post("/api/ask", json={"question": "When does the library open?"}).json
    assert gone["mode"] == "none" and "don't have any information" in gone["answer"]


@needs_search
def test_import_files_and_ask(client):
    sign_in(client, make_user("boss", "admin"))
    for name, expected in (("sample_knowledge.csv", 3), ("sample_timetable.csv", 3), ("sample_notice.txt", 1)):
        data = (ROOT / "sample_data" / name).read_bytes()
        res = client.post("/api/admin/modules/import", data={"file": (io.BytesIO(data), name)})
        assert res.status_code == 201 and res.json == {"added": expected}, res.json

    result = client.post("/api/ask", json={"question": "what do I do if I lose my ID card"}).json
    assert result["sources"][0] == "Lost ID card (sample)"
    assert "duplicate ID card form" in result["answer"]

    bus = client.post("/api/ask", json={"question": "when does the bus leave on saturday"}).json
    assert "1:15 PM" in bus["answer"]

    off_topic = client.post("/api/ask", json={"question": "who won the football world cup"}).json
    assert off_topic["mode"] == "none"
    assert client.post("/api/admin/reindex").json["chunks"] == 7


def test_import_rejects_other_file_types(client):
    sign_in(client, make_user("boss", "admin"))
    res = client.post("/api/admin/modules/import", data={"file": (io.BytesIO(b"%PDF"), "x.pdf")})
    assert res.status_code == 400


def test_question_length_is_limited(client):
    sign_in(client, make_user())
    assert client.post("/api/ask", json={"question": "x" * 501}).status_code == 422
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422


def test_bad_audio_is_a_friendly_error(client):
    sign_in(client, make_user())
    res = client.post("/api/transcribe", data=b"not a wav")
    assert res.status_code == 400 and "WAV" in res.json["error"]
