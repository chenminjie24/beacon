from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, RefreshRequest, TokenResponse
from app.security import create_token, decode_token, verify_password
from app.services.audit import write_audit

router = APIRouter(prefix='/auth', tags=['auth'])
settings = get_settings()


@router.post('/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户名或密码错误')

    access_token = create_token(user.username, settings.access_token_expire_minutes, token_type='access')
    refresh_token = create_token(user.username, settings.refresh_token_expire_minutes, token_type='refresh')

    write_audit(
        db,
        actor=user.username,
        action='USER_LOGIN',
        resource_type='user',
        resource_id=user.id,
        detail={},
    )
    db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post('/refresh', response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_data = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='刷新 token 无效') from exc

    if token_data.get('type') != 'refresh':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='token 类型错误')

    username = token_data.get('sub')
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在')

    access_token = create_token(user.username, settings.access_token_expire_minutes, token_type='access')
    refresh_token = create_token(user.username, settings.refresh_token_expire_minutes, token_type='refresh')
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)
