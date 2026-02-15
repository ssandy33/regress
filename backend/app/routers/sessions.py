import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.database import Session as SessionModel, get_db
from app.models.schemas import SessionCreate, SessionListResponse, SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(req: SessionCreate, db: DBSession = Depends(get_db)):
    """Save an analysis session."""
    now = datetime.now(timezone.utc).isoformat()
    session = SessionModel(
        id=str(uuid.uuid4()),
        name=req.name,
        config=json.dumps(req.config),
        results=None,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return SessionResponse(
        id=session.id,
        name=session.name,
        config=json.loads(session.config),
        results=json.loads(session.results) if session.results else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("", response_model=SessionListResponse)
def list_sessions(db: DBSession = Depends(get_db)):
    """List all sessions."""
    sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()

    return SessionListResponse(
        sessions=[
            SessionResponse(
                id=s.id,
                name=s.name,
                config=json.loads(s.config),
                results=json.loads(s.results) if s.results else None,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]
    )


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    """Get a session by ID."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse(
        id=session.id,
        name=session.name,
        config=json.loads(session.config),
        results=json.loads(session.results) if session.results else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, db: DBSession = Depends(get_db)):
    """Delete a session."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()
