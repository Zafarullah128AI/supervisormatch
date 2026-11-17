"""SupervisorMatch - complete project backend (FastAPI + HTML/CSS/JS frontend).

Run from the project root (ONE terminal, ONE url):
    pip install -r requirements.txt
    uvicorn backend.main:app --reload
Then open: http://127.0.0.1:8000  (the designed website is served by FastAPI)
API docs: http://127.0.0.1:8000/docs

Default accounts:
  Admin:    admin@sbbusba.edu.pk / admin123
  Teachers: any seeded teacher email / teacher123

FULL APPROVAL CYCLE (the complete process):
  1. Student submits an idea  -> system matches + ranks supervisors (idea: matched)
  2. Student sends a request  -> supervisor + admin are notified (idea: requested)
  3. Teacher accepts/rejects  -> accept moves it to "teacher_accepted",
                                  student + admin are notified
  4. Admin approves/rejects  -> approve assigns the supervisor finally
                                  (idea: assigned, load +1, everyone notified)
     Admin can also approve a still-pending request directly, or assign any
     supervisor manually (override). When one request is approved, all other
     open requests for that idea are closed automatically.
  5. Student rates the supervisor after assignment (feedback -> leaderboard).
"""

import csv
import io
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:  # run as: uvicorn backend.main:app (from project root)
    from backend import auth
    from backend.database import (
        DEFAULT_TEACHER_PASSWORD,
        create_user,
        get_conn,
        get_supervisors,
        get_user_by_email,
        notify,
        reset_demo,
        seed,
    )
    from backend.assistant import chat_reply, load_dotenv
    from backend.nlp import (
        check_idea_quality,
        check_uniqueness,
        classify_domain,
        detect_gibberish,
        match_idea,
    )
except ImportError:  # run as: uvicorn main:app (from inside backend/)
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import auth
    from database import (
        DEFAULT_TEACHER_PASSWORD,
        create_user,
        get_conn,
        get_supervisors,
        get_user_by_email,
        notify,
        reset_demo,
        seed,
    )
    from assistant import chat_reply, load_dotenv
    from nlp import (
        check_idea_quality,
        check_uniqueness,
        classify_domain,
        detect_gibberish,
        match_idea,
    )

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="SupervisorMatch API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.on_event("startup")
def startup():
    load_dotenv()  # reads GEMINI_API_KEY from a .env file if present
    seed()
    # Auto-open the browser only on a local laptop. On a hosted server
    # (Render sets AUTO_OPEN_BROWSER=0 in render.yaml) this is skipped.
    if os.environ.get("AUTO_OPEN_BROWSER", "1") == "1":
        _open_browser_when_ready()


def _open_browser_when_ready():
    """Open the website in the default browser automatically on startup,
    so the user does not have to type the address manually.
    Runs in a background thread; failures (e.g. headless servers) are ignored.
    Tip: for a demo without reload pop-ups, run without --reload.
    """
    import threading
    import time
    import webbrowser

    def _go():
        time.sleep(1.5)
        try:
            webbrowser.open("http://127.0.0.1:8000")
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def notify_admins(message):
    """Notify every admin user (used when a request needs final approval)."""
    conn = get_conn()
    rows = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
            (row[0], message),
        )
    conn.commit()
    conn.close()


# ------------------------------ models ------------------------------

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str  # student | supervisor (admin is seeded only)
    department: str = ""
    roll_no: str = ""
    semester: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class IdeaRequest(BaseModel):
    title: str
    description: str


class ChatRequest(BaseModel):
    message: str


class RequestCreate(BaseModel):
    idea_id: int
    supervisor_id: int
    message: str = ""


class ProfileUpdate(BaseModel):
    designation: str = ""
    research_interests: str = ""
    capacity: int = 5
    bio: str = ""


class SupervisorCreate(BaseModel):
    name: str
    email: str
    password: str = DEFAULT_TEACHER_PASSWORD
    department: str = ""
    designation: str = ""
    qualification: str = ""
    research_interests: str = ""
    capacity: int = 5


class SupervisorUpdate(BaseModel):
    name: str = ""
    department: str = ""
    designation: str = ""
    qualification: str = ""
    research_interests: str = ""
    capacity: int = 5
    is_active: int = 1


class FeedbackCreate(BaseModel):
    supervisor_id: int
    idea_id: int
    rating: int
    comment: str = ""


class ManualAssign(BaseModel):
    idea_id: int
    supervisor_id: int


# ------------------------------ auth deps ------------------------------

def _public_user(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "department": row["department"],
        "campus": row["campus"],
    }


def get_current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    data = auth.decode_token(authorization[7:])
    if data is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND is_active = 1", (data["sub"],)
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(row)


def require_role(role):
    def checker(user=Depends(get_current_user)):
        if user["role"] != role:
            raise HTTPException(status_code=403, detail=f"Requires {role} role")
        return user

    return checker


# ------------------------------ website + health ------------------------------

@app.get("/")
def website_root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "service": "SupervisorMatch API",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "SupervisorMatch API"}


@app.get("/public/stats")
def public_stats():
    """Live numbers for the landing page (no login needed)."""
    conn = get_conn()
    supervisors = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'supervisor' AND is_active = 1"
    ).fetchone()[0]
    departments = conn.execute(
        "SELECT COUNT(DISTINCT department) FROM users"
        " WHERE role = 'supervisor' AND department != ''"
    ).fetchone()[0]
    ideas = conn.execute("SELECT COUNT(*) FROM project_ideas").fetchone()[0]
    assignments = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status = 'approved'"
    ).fetchone()[0]
    conn.close()
    return {
        "supervisors": supervisors,
        "departments": departments,
        "ideas": ideas,
        "assignments": assignments,
    }


# ------------------------------ auth ------------------------------

@app.post("/auth/register")
def register(body: RegisterRequest):
    if body.role not in ("student", "supervisor"):
        raise HTTPException(status_code=400, detail="Role must be student or supervisor")
    if get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = create_user(
        body.name, body.email, auth.hash_password(body.password),
        body.role, department=body.department,
    )
    conn = get_conn()
    if body.role == "supervisor":
        conn.execute(
            "INSERT INTO supervisor_profiles (user_id, research_interests)"
            " VALUES (?, ?)",
            (user_id, ""),
        )
    else:
        conn.execute(
            "INSERT INTO student_profiles (user_id, roll_no, semester)"
            " VALUES (?, ?, ?)",
            (user_id, body.roll_no, body.semester),
        )
    conn.commit()
    conn.close()
    return {"message": "Registered successfully", "user_id": user_id}


@app.post("/auth/login")
def login(body: LoginRequest):
    user = get_user_by_email(body.email)
    if user is None or user["is_active"] != 1:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"token": auth.create_token(user["id"], user["role"]), "user": _public_user(user)}


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return _public_user(user)


# ------------------------------ directory + leaderboard ------------------------------

@app.get("/supervisors")
def list_supervisors(search: str = "", department: str = ""):
    return get_supervisors(search=search or None, department=department or None)


@app.get("/supervisors/{supervisor_id}")
def supervisor_detail(supervisor_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT u.id AS user_id, u.name, u.email, u.department, u.campus,"
        " p.designation, p.qualification, p.research_interests, p.capacity,"
        " p.current_load, p.bio, p.record_type, p.email_status,"
        " (SELECT AVG(rating) FROM feedback WHERE supervisor_id = u.id) AS avg_rating,"
        " (SELECT COUNT(*) FROM feedback WHERE supervisor_id = u.id) AS feedback_count"
        " FROM users u JOIN supervisor_profiles p ON p.user_id = u.id"
        " WHERE u.id = ? AND u.role = 'supervisor'",
        (supervisor_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Supervisor not found")
    return dict(row)


@app.get("/leaderboard")
def leaderboard(user=Depends(get_current_user)):
    """Supervisors ranked by rating, then assignments, then matches."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.id, u.name, u.department, p.designation, p.record_type,"
        " p.capacity, p.current_load,"
        " (SELECT COUNT(*) FROM matches WHERE supervisor_id = u.id) AS total_matches,"
        " (SELECT COUNT(*) FROM requests WHERE supervisor_id = u.id"
        "  AND status = 'approved') AS assignments,"
        " (SELECT AVG(rating) FROM feedback WHERE supervisor_id = u.id) AS avg_rating,"
        " (SELECT COUNT(*) FROM feedback WHERE supervisor_id = u.id) AS feedback_count"
        " FROM users u JOIN supervisor_profiles p ON p.user_id = u.id"
        " WHERE u.role = 'supervisor' AND u.is_active = 1"
        " ORDER BY COALESCE(avg_rating, 0) DESC, assignments DESC, total_matches DESC"
    ).fetchall()
    conn.close()
    result = []
    for rank, row in enumerate(rows, start=1):
        item = dict(row)
        item["rank"] = rank
        item["avg_rating"] = round(item["avg_rating"], 2) if item["avg_rating"] is not None else None
        result.append(item)
    return result


# ------------------------------ student ------------------------------

@app.post("/student/ideas/analyze")
def analyze_idea(body: IdeaRequest, user=Depends(require_role("student"))):
    """v5: check an idea BEFORE submitting it - quality, originality and
    whether it looks like random characters. Nothing is saved."""
    idea_text = f"{body.title} {body.description}".strip()
    quality = check_idea_quality(body.title, body.description)
    return {
        "quality": quality,
        "uniqueness": check_uniqueness(idea_text),
        "gibberish": quality["gibberish"],
    }


@app.post("/student/ideas")
def submit_idea(body: IdeaRequest, user=Depends(require_role("student"))):
    idea_text = f"{body.title} {body.description}".strip()
    # v5: random-letter input (for example 'sdfgdsjfgfsdhfsdfsdfsdifkj')
    # is rejected with a clear message instead of producing fake matches.
    gib = detect_gibberish(idea_text)
    if gib["is_gibberish"]:
        raise HTTPException(
            status_code=400,
            detail="This looks like random characters, not a project idea. "
                   "Please describe your project in words.",
        )
    domain = classify_domain(idea_text)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO project_ideas (student_id, title, description, domain, status)"
        " VALUES (?, ?, ?, ?, 'matched')",
        (user["id"], body.title, body.description, domain),
    )
    idea_id = cur.lastrowid
    conn.commit()
    conn.close()
    matches, method = match_idea(idea_text, get_supervisors(), top_n=5)
    conn = get_conn()
    for rank, m in enumerate(matches, start=1):
        conn.execute(
            "INSERT INTO matches (idea_id, supervisor_id, score, rank, explanation)"
            " VALUES (?, ?, ?, ?, ?)",
            (idea_id, m["supervisor_id"], m["score"], rank, m["explanation"]),
        )
    conn.commit()
    conn.close()
    return {
        "idea_id": idea_id, "domain": domain, "method": method,
        "matches": matches,
        "quality": check_idea_quality(body.title, body.description),
        "uniqueness": check_uniqueness(idea_text),
    }


@app.get("/student/ideas")
def my_ideas(user=Depends(require_role("student"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM project_ideas WHERE student_id = ? ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/student/ideas/{idea_id}/matches")
def idea_matches(idea_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    idea = conn.execute("SELECT * FROM project_ideas WHERE id = ?", (idea_id,)).fetchone()
    if idea is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Idea not found")
    if user["role"] == "student" and idea["student_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not your idea")
    rows = conn.execute(
        "SELECT m.*, u.name, u.email, p.designation, p.research_interests,"
        " p.record_type FROM matches m JOIN users u ON u.id = m.supervisor_id"
        " JOIN supervisor_profiles p ON p.user_id = u.id"
        " WHERE m.idea_id = ? ORDER BY m.rank",
        (idea_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/student/requests")
def send_request(body: RequestCreate, user=Depends(require_role("student"))):
    conn = get_conn()
    idea = conn.execute("SELECT * FROM project_ideas WHERE id = ?", (body.idea_id,)).fetchone()
    if idea is None or idea["student_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not your idea")
    existing = conn.execute(
        "SELECT id FROM requests WHERE idea_id = ? AND supervisor_id = ?"
        " AND status IN ('pending', 'teacher_accepted')",
        (body.idea_id, body.supervisor_id),
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Request already open for this supervisor")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests (idea_id, student_id, supervisor_id, message)"
        " VALUES (?, ?, ?, ?)",
        (body.idea_id, user["id"], body.supervisor_id, body.message),
    )
    request_id = cur.lastrowid
    conn.execute(
        "UPDATE project_ideas SET status = 'requested' WHERE id = ?", (body.idea_id,)
    )
    conn.commit()
    conn.close()
    # Step 2 notifications: teacher + admin both see it immediately.
    notify(body.supervisor_id,
           f"New supervision request from {user['name']} for '{idea['title']}'.")
    notify_admins(
        f"New request: {user['name']} asked a supervisor for '{idea['title']}'.")
    return {"message": "Request sent", "request_id": request_id}


@app.get("/student/requests")
def my_requests(user=Depends(require_role("student"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, u.name AS supervisor_name, p.title AS idea_title"
        " FROM requests r JOIN users u ON u.id = r.supervisor_id"
        " JOIN project_ideas p ON p.id = r.idea_id"
        " WHERE r.student_id = ? ORDER BY r.id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/student/requests/{request_id}/cancel")
def cancel_request(request_id: int, user=Depends(require_role("student"))):
    conn = get_conn()
    req = conn.execute(
        "SELECT * FROM requests WHERE id = ? AND student_id = ?",
        (request_id, user["id"]),
    ).fetchone()
    if req is None or req["status"] not in ("pending", "teacher_accepted"):
        conn.close()
        raise HTTPException(status_code=404, detail="Open request not found")
    conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = ?", (request_id,))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE idea_id = ? AND status IN ('pending', 'teacher_accepted')",
        (req["idea_id"],),
    ).fetchone()[0]
    if remaining == 0:
        conn.execute(
            "UPDATE project_ideas SET status = 'matched' WHERE id = ?", (req["idea_id"],)
        )
    conn.commit()
    conn.close()
    notify(req["supervisor_id"],
           f"Request for idea #{req['idea_id']} was cancelled by the student.")
    return {"message": "Request cancelled"}


@app.post("/feedback")
def submit_feedback(body: FeedbackCreate, user=Depends(require_role("student"))):
    conn = get_conn()
    conn.execute(
        "INSERT INTO feedback (student_id, supervisor_id, idea_id, rating, comment)"
        " VALUES (?, ?, ?, ?, ?)",
        (user["id"], body.supervisor_id, body.idea_id, body.rating, body.comment),
    )
    conn.commit()
    conn.close()
    return {"message": "Feedback saved"}


# ------------------------------ supervisor ------------------------------

@app.get("/supervisor/requests")
def incoming_requests(user=Depends(require_role("supervisor"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, u.name AS student_name, p.title AS idea_title,"
        " p.description AS idea_description FROM requests r"
        " JOIN users u ON u.id = r.student_id"
        " JOIN project_ideas p ON p.id = r.idea_id"
        " WHERE r.supervisor_id = ? ORDER BY r.id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _teacher_decide(request_id, user, decision):
    conn = get_conn()
    req = conn.execute(
        "SELECT * FROM requests WHERE id = ? AND supervisor_id = ?",
        (request_id, user["id"]),
    ).fetchone()
    if req is None or req["status"] != "pending":
        conn.close()
        raise HTTPException(status_code=404, detail="Pending request not found")
    idea = conn.execute(
        "SELECT * FROM project_ideas WHERE id = ?", (req["idea_id"],)
    ).fetchone()
    if decision == "teacher_accepted":
        conn.execute(
            "UPDATE requests SET status = 'teacher_accepted' WHERE id = ?", (request_id,)
        )
        conn.execute(
            "UPDATE project_ideas SET status = 'awaiting_approval' WHERE id = ?",
            (req["idea_id"],),
        )
    else:
        conn.execute(
            "UPDATE requests SET status = 'rejected' WHERE id = ?", (request_id,)
        )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE idea_id = ?"
            " AND status IN ('pending', 'teacher_accepted')",
            (req["idea_id"],),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                "UPDATE project_ideas SET status = 'matched' WHERE id = ?",
                (req["idea_id"],),
            )
    conn.commit()
    conn.close()
    if decision == "teacher_accepted":
        notify(req["student_id"],
               f"{user['name']} accepted your request for '{idea['title']}'."
               " Waiting for admin approval.")
        notify_admins(
            f"{user['name']} accepted a request for '{idea['title']}'."
            " Final approval is pending.")
    else:
        notify(req["student_id"],
               f"{user['name']} rejected your request for '{idea['title']}'.")
    return {"message": f"Request {decision}"}


@app.post("/supervisor/requests/{request_id}/accept")
def teacher_accept(request_id: int, user=Depends(require_role("supervisor"))):
    return _teacher_decide(request_id, user, "teacher_accepted")


@app.post("/supervisor/requests/{request_id}/reject")
def teacher_reject(request_id: int, user=Depends(require_role("supervisor"))):
    return _teacher_decide(request_id, user, "rejected")


@app.get("/supervisor/students")
def assigned_students(user=Depends(require_role("supervisor"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.name AS student_name, u.email, p.title AS idea_title,"
        " r.created_at FROM requests r JOIN users u ON u.id = r.student_id"
        " JOIN project_ideas p ON p.id = r.idea_id"
        " WHERE r.supervisor_id = ? AND r.status = 'approved' ORDER BY r.id DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.put("/supervisor/profile")
def update_profile(body: ProfileUpdate, user=Depends(require_role("supervisor"))):
    conn = get_conn()
    conn.execute(
        "UPDATE supervisor_profiles SET designation = ?, research_interests = ?,"
        " capacity = ?, bio = ? WHERE user_id = ?",
        (body.designation, body.research_interests, body.capacity, body.bio, user["id"]),
    )
    conn.commit()
    conn.close()
    return {"message": "Profile updated (matching uses the new interests immediately)"}


# ------------------------------ admin ------------------------------

def _finalize_approval(request_id, approve, admin_user):
    """Shared by admin approve/reject: closes the whole cycle for one idea."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if req is None or req["status"] not in ("pending", "teacher_accepted"):
        conn.close()
        raise HTTPException(status_code=404, detail="Open request not found")
    idea = conn.execute(
        "SELECT * FROM project_ideas WHERE id = ?", (req["idea_id"],)
    ).fetchone()
    student = conn.execute("SELECT * FROM users WHERE id = ?", (req["student_id"],)).fetchone()
    supervisor = conn.execute("SELECT * FROM users WHERE id = ?", (req["supervisor_id"],)).fetchone()
    if approve:
        conn.execute(
            "UPDATE requests SET status = 'approved' WHERE id = ?", (request_id,)
        )
        conn.execute(
            "UPDATE project_ideas SET status = 'assigned' WHERE id = ?",
            (req["idea_id"],),
        )
        conn.execute(
            "UPDATE supervisor_profiles SET current_load = current_load + 1"
            " WHERE user_id = ?",
            (req["supervisor_id"],),
        )
        # Close every other open request for the same idea.
        conn.execute(
            "UPDATE requests SET status = 'closed' WHERE idea_id = ?"
            " AND status IN ('pending', 'teacher_accepted') AND id != ?",
            (req["idea_id"], request_id),
        )
    else:
        conn.execute(
            "UPDATE requests SET status = 'admin_rejected' WHERE id = ?", (request_id,)
        )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE idea_id = ?"
            " AND status IN ('pending', 'teacher_accepted')",
            (req["idea_id"],),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute(
                "UPDATE project_ideas SET status = 'matched' WHERE id = ?",
                (req["idea_id"],),
            )
    conn.commit()
    conn.close()
    if approve:
        notify(req["student_id"],
               f"Approved! {supervisor['name']} is now your supervisor for '{idea['title']}'.")
        notify(req["supervisor_id"],
               f"Admin approved you as supervisor for '{idea['title']}'"
               f" (student: {student['name']}).")
    else:
        notify(req["student_id"],
               f"Admin did not approve the request for '{idea['title']}'.")
        notify(req["supervisor_id"],
               f"Admin did not approve the request for '{idea['title']}'.")
    return {"message": "Request approved and assigned" if approve else "Request rejected by admin"}


@app.post("/admin/requests/{request_id}/approve")
def admin_approve(request_id: int, user=Depends(require_role("admin"))):
    return _finalize_approval(request_id, True, user)


@app.post("/admin/requests/{request_id}/reject")
def admin_reject(request_id: int, user=Depends(require_role("admin"))):
    return _finalize_approval(request_id, False, user)


@app.get("/admin/pending-approvals")
def pending_approvals(user=Depends(require_role("admin"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, s.name AS student_name, t.name AS supervisor_name,"
        " p.title AS idea_title FROM requests r"
        " JOIN users s ON s.id = r.student_id JOIN users t ON t.id = r.supervisor_id"
        " JOIN project_ideas p ON p.id = r.idea_id"
        " WHERE r.status IN ('pending', 'teacher_accepted') ORDER BY r.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/admin/ideas")
def admin_ideas(user=Depends(require_role("admin"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.*, u.name AS student_name,"
        " (SELECT COUNT(*) FROM requests WHERE idea_id = p.id) AS request_count"
        " FROM project_ideas p JOIN users u ON u.id = p.student_id ORDER BY p.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/admin/assign")
def admin_manual_assign(body: ManualAssign, user=Depends(require_role("admin"))):
    """Admin override: assign any supervisor to any idea immediately."""
    conn = get_conn()
    idea = conn.execute("SELECT * FROM project_ideas WHERE id = ?", (body.idea_id,)).fetchone()
    sup = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'supervisor'",
        (body.supervisor_id,),
    ).fetchone()
    if idea is None or sup is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Idea or supervisor not found")
    if idea["status"] == "assigned":
        conn.close()
        raise HTTPException(status_code=400, detail="Idea already assigned")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests (idea_id, student_id, supervisor_id, message, status)"
        " VALUES (?, ?, ?, 'Assigned directly by admin', 'approved')",
        (body.idea_id, idea["student_id"], body.supervisor_id),
    )
    conn.execute(
        "UPDATE project_ideas SET status = 'assigned' WHERE id = ?", (body.idea_id,)
    )
    conn.execute(
        "UPDATE supervisor_profiles SET current_load = current_load + 1"
        " WHERE user_id = ?",
        (body.supervisor_id,),
    )
    conn.execute(
        "UPDATE requests SET status = 'closed' WHERE idea_id = ?"
        " AND status IN ('pending', 'teacher_accepted')",
        (body.idea_id,),
    )
    conn.commit()
    conn.close()
    notify(idea["student_id"],
           f"Admin assigned {sup['name']} as your supervisor for '{idea['title']}'.")
    notify(body.supervisor_id,
           f"Admin assigned you as supervisor for '{idea['title']}'.")
    return {"message": "Supervisor assigned by admin"}


# ------------------------------ assistant chatbot (v6) ------------------------------
# Gemini-powered when GEMINI_API_KEY is set (see backend/assistant.py),
# rule-based fallback otherwise. The reply says which engine answered.

@app.post("/assistant/chat")
def assistant_chat(body: ChatRequest, user=Depends(get_current_user)):
    """Discuss titles/descriptions with the AI assistant (v6)."""
    return chat_reply(user, body.message)


@app.get("/admin/stats")
def admin_stats(user=Depends(require_role("admin"))):
    conn = get_conn()
    one = lambda q, p=(): conn.execute(q, p).fetchone()[0]
    domains = conn.execute(
        "SELECT domain, COUNT(*) AS count FROM project_ideas GROUP BY domain"
        " ORDER BY count DESC"
    ).fetchall()
    top = conn.execute(
        "SELECT u.name, COUNT(m.id) AS matches FROM matches m"
        " JOIN users u ON u.id = m.supervisor_id GROUP BY u.id"
        " ORDER BY matches DESC LIMIT 5"
    ).fetchall()
    result = {
        "total_students": one("SELECT COUNT(*) FROM users WHERE role = 'student'"),
        "total_supervisors": one("SELECT COUNT(*) FROM users WHERE role = 'supervisor' AND is_active = 1"),
        "total_ideas": one("SELECT COUNT(*) FROM project_ideas"),
        "total_matches": one("SELECT COUNT(*) FROM matches"),
        "total_assignments": one("SELECT COUNT(*) FROM requests WHERE status = 'approved'"),
        "pending_requests": one("SELECT COUNT(*) FROM requests WHERE status = 'pending'"),
        "pending_approvals": one("SELECT COUNT(*) FROM requests WHERE status = 'teacher_accepted'"),
        "domain_distribution": [dict(r) for r in domains],
        "top_supervisors": [dict(r) for r in top],
        # v5: charts data - request status counts and supervisor load.
        "status_counts": {
            r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM requests GROUP BY status"
            ).fetchall()
        },
        "load_distribution": [
            {"name": s["name"], "current_load": s.get("current_load") or 0,
             "capacity": s.get("capacity") or 5}
            for s in sorted(get_supervisors(), key=lambda x: -(x.get("current_load") or 0))[:10]
        ],
    }
    conn.close()
    return result


@app.post("/admin/reset-demo")
def admin_reset_demo(user=Depends(require_role("admin"))):
    """Exhibition helper: wipe all demo records and re-seed (admin +
    demo student + 100 supervisors) so a judge can try the full approval
    cycle again from a clean slate. Admin-only."""
    reset_demo()
    return {"message": "Demo data reset — admin, demo student and 100 supervisors re-seeded."}


@app.get("/admin/supervisors")
def admin_list_supervisors(user=Depends(require_role("admin"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.id, u.name, u.email, u.department, u.is_active,"
        " p.designation, p.research_interests, p.capacity, p.current_load,"
        " p.record_type FROM users u JOIN supervisor_profiles p ON p.user_id = u.id"
        " WHERE u.role = 'supervisor' ORDER BY u.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/admin/supervisors")
def admin_add_supervisor(body: SupervisorCreate, user=Depends(require_role("admin"))):
    if get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=400, detail="Email already exists")
    user_id = create_user(
        body.name, body.email, auth.hash_password(body.password),
        "supervisor", department=body.department,
    )
    conn = get_conn()
    conn.execute(
        "INSERT INTO supervisor_profiles (user_id, designation, qualification,"
        " research_interests, capacity) VALUES (?, ?, ?, ?, ?)",
        (user_id, body.designation, body.qualification,
         body.research_interests, body.capacity),
    )
    conn.commit()
    conn.close()
    return {"message": "Supervisor added", "user_id": user_id}


@app.put("/admin/supervisors/{supervisor_id}")
def admin_edit_supervisor(supervisor_id: int, body: SupervisorUpdate,
                          user=Depends(require_role("admin"))):
    conn = get_conn()
    if body.name:
        conn.execute("UPDATE users SET name = ?, department = ?, is_active = ?"
                     " WHERE id = ?", (body.name, body.department, body.is_active, supervisor_id))
    conn.execute(
        "UPDATE supervisor_profiles SET designation = ?, qualification = ?,"
        " research_interests = ?, capacity = ? WHERE user_id = ?",
        (body.designation, body.qualification, body.research_interests,
         body.capacity, supervisor_id),
    )
    conn.commit()
    conn.close()
    return {"message": "Supervisor updated"}


@app.delete("/admin/supervisors/{supervisor_id}")
def admin_delete_supervisor(supervisor_id: int, user=Depends(require_role("admin"))):
    conn = get_conn()
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (supervisor_id,))
    conn.commit()
    conn.close()
    return {"message": "Supervisor deactivated (soft delete)"}


@app.get("/admin/students")
def admin_list_students(user=Depends(require_role("admin"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.id, u.name, u.email, u.department, s.roll_no, s.semester"
        " FROM users u LEFT JOIN student_profiles s ON s.user_id = u.id"
        " WHERE u.role = 'student' ORDER BY u.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/admin/assignments")
def admin_assignments(user=Depends(require_role("admin"))):
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.id, s.name AS student_name, t.name AS supervisor_name,"
        " p.title AS idea_title, p.domain, r.created_at FROM requests r"
        " JOIN users s ON s.id = r.student_id JOIN users t ON t.id = r.supervisor_id"
        " JOIN project_ideas p ON p.id = r.idea_id"
        " WHERE r.status = 'approved' ORDER BY r.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/admin/export/assignments")
def export_assignments(user=Depends(require_role("admin"))):
    rows = admin_assignments(user)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["id", "student_name", "supervisor_name", "idea_title",
                         "domain", "created_at"])
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=assignments.csv"},
    )


# ------------------------------ notifications & evaluation ------------------------------

@app.get("/notifications")
def my_notifications(user=Depends(get_current_user)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 30",
        (user["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/notifications/read")
def read_notifications(user=Depends(get_current_user)):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return {"message": "All notifications marked as read"}


@app.get("/evaluation")
def evaluation(user=Depends(get_current_user)):
    """Roadmap Phase 10: metrics comparing TF-IDF-only vs full pipeline."""
    try:
        from backend.evaluation import run_evaluation
    except ImportError:
        from evaluation import run_evaluation
    return run_evaluation()
