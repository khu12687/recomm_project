import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from .repository import AuthRepository


logger = logging.getLogger(__name__)


class AuthError(Exception):
    def __init__(
        self,
        status_code,
        detail,
        retry_after=None,
    ):
        super().__init__(detail)

        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after

class AuthService:
    def __init__(self):
        self.repository = AuthRepository()
        self.password_hasher = PasswordHash.recommended()

        # 존재하지 않는 계정도 비밀번호 해시 검증을 수행한다.
        self.dummy_hash = self.password_hasher.hash(
            secrets.token_urlsafe(32)
        )

    def initialize(self):
        self.repository.initialize()

    def close(self):
        self.repository.close()

    def health(self):
        self.repository.health()
        return {"status": "ok"}

    @staticmethod
    def user_response(user):
        return {
            "id": user.id,
            "email": user.email,
            "is_verified": user.is_verified,
            "created_at": user.created_at,
        }

    def _send_code(self, email):
        # 앞자리 0을 포함하는 6자리 코드.
        code = f"{secrets.randbelow(1_000_000):06d}"

        timing = self.repository.issue_code(
            email,
            code,
        )

        now = datetime.now(timezone.utc)

        return {
            "message": "인증코드를 이메일로 발송했습니다.",
            "server_time": now,
            "expires_at": now + timedelta(
                seconds=timing["expires_in"]
            ),
            "resend_available_at": now + timedelta(
                seconds=timing["resend_after"]
            ),
            "attempts_remaining": 5,
        }

    def signup(self, email, password):
        with self.repository.email_lock(email):
            existing = self.repository.find_by_email(
                email
            )

            if existing is not None:
                raise AuthError(
                    409,
                    "이미 가입된 이메일입니다. 미인증 계정이면 인증코드를 재전송하세요.",
                )

            password_hash = self.password_hasher.hash(
                password
            )

            self.repository.create_user(
                email,
                password_hash,
            )

            # 메일 발송 실패 시 계정은 미인증 상태로 유지된다.
            # 사용자는 resend-code로 다시 발송할 수 있다.
            return self._send_code(email)

    def resend_code(self, email):
        with self.repository.email_lock(email):
            user = self.repository.find_by_email(email)

            if user is None:
                raise AuthError(
                    404,
                    "먼저 회원가입을 진행하세요.",
                )

            if user.is_verified:
                raise AuthError(
                    409,
                    "이미 인증된 이메일입니다.",
                )

            return self._send_code(email)

    def verify_email(self, email, code):
        with self.repository.email_lock(email):
            user = self.repository.find_by_email(email)

            if user is None:
                raise AuthError(
                    404,
                    "먼저 회원가입을 진행하세요.",
                )

            if user.is_verified:
                self.repository.delete_code(email)
                return {
                    "message": "이미 인증된 이메일입니다."
                }

            self.repository.check_code(email, code)

            # DB에 먼저 인증 완료를 저장한다.
            self.repository.mark_verified(user.id)

            # 성공 코드를 제거해 재사용할 수 없게 한다.
            self.repository.delete_code(email)

            return {
                "message": "이메일 인증이 완료되었습니다."
            }

    def login(self, email, password):
        user = self.repository.find_by_email(email)

        saved_hash = (
            user.password_hash
            if user is not None
            else self.dummy_hash
        )

        password_matches = self.password_hasher.verify(
            password,
            saved_hash,
        )

        if user is None or not password_matches:
            raise AuthError(
                401,
                "이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        if not user.is_verified:
            raise AuthError(
                403,
                "이메일 인증을 먼저 완료하세요.",
            )

        now = datetime.now(timezone.utc)
        expires_in = (
            self.repository.jwt_minutes * 60
        )

        token = jwt.encode(
            {
                "sub": str(user.id),
                "iat": now,
                "exp": now + timedelta(
                    seconds=expires_in
                ),
                "iss": "recomm-project",
                "aud": "recomm-api",
                "token_type": "access",
            },
            self.repository.jwt_secret,
            algorithm="HS256",
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    def me(self, token):
        try:
            payload = jwt.decode(
                token,
                self.repository.jwt_secret,
                algorithms=["HS256"],
                issuer="recomm-project",
                audience="recomm-api",
                options={
                    "require": [
                        "sub",
                        "iat",
                        "exp",
                        "iss",
                        "aud",
                    ]
                },
            )

            if payload.get("token_type") != "access":
                raise ValueError("Invalid token type")

            user_id = int(payload["sub"])

        except (
            InvalidTokenError,
            ValueError,
            TypeError,
            KeyError,
        ):
            raise AuthError(
                401,
                "토큰이 유효하지 않거나 만료되었습니다. 다시 로그인하세요.",
            )

        user = self.repository.find_by_id(user_id)

        if user is None or not user.is_verified:
            raise AuthError(
                401,
                "인증된 회원을 찾을 수 없습니다.",
            )

        return self.user_response(user)

    def execute(self, operation, *args):
        """저장소 오류를 서비스 오류로 변환한다."""
        from .repository import RepositoryError
        from redis.exceptions import RedisError
        from sqlalchemy.exc import SQLAlchemyError

        try:
            return getattr(self, operation)(*args)

        except AuthError:
            raise

        except RepositoryError as error:
            if error.status_code >= 500:
                # repository에서 발생한 원인 예외까지 기록한다.
                # 비밀번호와 인증코드는 직접 출력하지 않는다.
                logger.exception(
                    "인증 처리 실패: operation=%s, status=%s",
                    operation,
                    error.status_code,
                )

            raise AuthError(
                status_code=error.status_code,
                detail=error.detail,
                retry_after=error.retry_after,
            ) from error

        except (RedisError, SQLAlchemyError) as error:
            logger.exception(
                "인증 저장소 연결 또는 처리 실패: operation=%s",
                operation,
            )

            raise AuthError(
                status_code=503,
                detail=(
                    "인증 저장소를 일시적으로 사용할 수 없습니다. "
                    "잠시 후 다시 시도하세요."
                ),
            ) from error