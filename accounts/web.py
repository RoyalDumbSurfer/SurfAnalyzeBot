"""Authentication checks shared by HTML and API routes."""
import hmac
import secrets

from fastapi import HTTPException, Request


def current_user(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def csrf_token(request: Request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, submitted: str):
    expected = request.session.get("csrf", "")
    supplied = request.headers.get("x-csrf-token", submitted)
    if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(status_code=403, detail="Please reload the page and try again.")


def owned_job(request: Request, job_id: str):
    user = current_user(request)
    job = request.app.state.job_manager.get_job(job_id, owner_user_id=user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Not found")
    return job
