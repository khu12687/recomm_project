import hashlib
import hmac
import logging
import os
import smtplib
import ssl
import time

from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage
from uuid import uuid4

from redis import Redis
from redis.exceptions import LockError

from sqlalchemy import URL, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .model import Base, User


logger = logging.getLogger(__name__)


@dataclass
class RepositoryError(Exception):
    status_code: int
    detail: str
    retry_after: int | None = None


class AuthRepository:
    CODE_TTL = 300
    RESEND_INTERVAL = 60
    HOURLY_LIMIT = 5
    MAX_ATTEMPTS = 5

    # 이메일별 최근 1시간 발송 최대 5회.
    # 발송 간격 60초, 코드 유효시간 300초.
    ISSUE_SCRIPT = """
    local code_key = KEYS[1]
    local cooldown_key = KEYS[2]
    local history_key = KEYS[3]

    local now = tonumber(ARGV[1])
    local member = ARGV[2]
    local digest = ARGV[3]

    local cooldown = redis.call(
        'TTL',
        cooldown_key
    )

    if cooldown > 0 then
        return {0, cooldown}
    end

    redis.call(
        'ZREMRANGEBYSCORE',
        history_key,
        '-inf',
        now - 3600
    )

    if redis.call('ZCARD', history_key) >= 5 then
        local oldest = redis.call(
            'ZRANGE',
            history_key,
            0,
            0,
            'WITHSCORES'
        )

        local wait = math.max(
            1,
            math.ceil(
                tonumber(oldest[2]) + 3600 - now
            )
        )

        return {-1, wait}
    end

    redis.call(
        'ZADD',
        history_key,
        now,
        member
    )

    redis.call(
        'EXPIRE',
        history_key,
        3600
    )

    redis.call(
        'SET',
        cooldown_key,
        member,
        'EX',
        60
    )

    redis.call('DEL', code_key)

    redis.call(
        'HSET',
        code_key,
        'digest', digest,
        'attempts', 0,
        'generation', member
    )

    redis.call(
        'EXPIRE',
        code_key,
        300
    )

    return {1, 0}
    """

    # 코드 확인은 최대 5회.
    # 성공 코드는 DB 인증 완료 저장 후 삭제한다.
    VERIFY_SCRIPT = """
    if redis.call('EXISTS', KEYS[1]) == 0 then
        return {-1, 0}
    end

    local attempts = tonumber(
        redis.call(
            'HGET',
            KEYS[1],
            'attempts'
        ) or '0'
    )

    if attempts >= 5 then
        return {-2, 0}
    end

    attempts = redis.call(
        'HINCRBY',
        KEYS[1],
        'attempts',
        1
    )

    local expected = redis.call(
        'HGET',
        KEYS[1],
        'digest'
    )

    if expected == ARGV[1] then
        return {1, 5 - attempts}
    end

    return {0, 5 - attempts}
    """

    # 메일 발송 실패 시 해당 발송의 기록만 정리한다.
    CLEANUP_FAILED_SEND_SCRIPT = """
    if redis.call(
        'HGET',
        KEYS[1],
        'generation'
    ) == ARGV[1] then
        redis.call('DEL', KEYS[1])
    end

    if redis.call(
        'GET',
        KEYS[2]
    ) == ARGV[1] then
        redis.call('DEL', KEYS[2])
    end

    redis.call(
        'ZREM',
        KEYS[3],
        ARGV[1]
    )

    return 1
    """

    def __init__(self):
        self.jwt_secret = os.environ["JWT_SECRET"]

        self.jwt_minutes = int(
            os.environ["JWT_EXPIRE_MINUTES"]
        )

        if len(self.jwt_secret.encode()) < 32:
            raise RuntimeError(
                "JWT_SECRET은 32바이트 이상으로 설정하세요."
            )

        if self.jwt_minutes <= 0:
            raise RuntimeError(
                "JWT_EXPIRE_MINUTES는 양수여야 합니다."
            )

        database_url = URL.create(
            drivername="postgresql+psycopg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            database=os.environ["POSTGRES_DB"],
        )

        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 5,
            },
        )

        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

        self.redis = Redis(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ["REDIS_PORT"]),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    def initialize(self):
        # 기존 테이블과 데이터는 유지한다.
        Base.metadata.create_all(self.engine)
        self.redis.ping()

    def close(self):
        self.redis.close()
        self.engine.dispose()

    def health(self):
        with self.engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

        self.redis.ping()

    def _keys(self, email):
        identifier = hashlib.sha256(
            email.encode()
        ).hexdigest()

        prefix = f"auth:{{{identifier}}}"

        return (
            f"{prefix}:code",
            f"{prefix}:cooldown",
            f"{prefix}:history",
            f"{prefix}:lock",
        )

    @contextmanager
    def email_lock(self, email):
        lock = self.redis.lock(
            self._keys(email)[3],
            timeout=60,
            blocking_timeout=3,
        )

        if not lock.acquire():
            raise RepositoryError(
                409,
                "같은 이메일의 요청을 처리 중입니다. "
                "잠시 후 다시 시도하세요.",
            )

        try:
            yield

        finally:
            try:
                lock.release()

            except LockError:
                pass

    def find_by_email(self, email):
        with self.session_factory() as session:
            return session.scalar(
                select(User).where(
                    User.email == email
                )
            )

    def find_by_id(self, user_id):
        with self.session_factory() as session:
            return session.get(
                User,
                user_id,
            )

    def create_user(self, email, password_hash):
        try:
            with self.session_factory.begin() as session:
                user = User(
                    email=email,
                    password_hash=password_hash,
                )

                session.add(user)
                session.flush()
                session.refresh(user)

                return user

        except IntegrityError:
            raise RepositoryError(
                409,
                "이미 가입된 이메일입니다. "
                "미인증 계정이면 인증코드를 재전송하세요.",
            )

    def mark_verified(self, user_id):
        with self.session_factory.begin() as session:
            user = session.get(
                User,
                user_id,
            )

            if user is None:
                raise RepositoryError(
                    404,
                    "회원을 찾을 수 없습니다.",
                )

            user.is_verified = True

    def _code_digest(self, email, code):
        # Redis에는 인증코드 원문 대신 HMAC을 저장한다.
        message = (
            f"email-code:{email}:{code}"
        ).encode()

        return hmac.new(
            self.jwt_secret.encode(),
            message,
            hashlib.sha256,
        ).hexdigest()

    def issue_code(self, email, code):
        (
            code_key,
            cooldown_key,
            history_key,
            _,
        ) = self._keys(email)

        generation = uuid4().hex

        status, retry_after = self.redis.eval(
            self.ISSUE_SCRIPT,
            3,
            code_key,
            cooldown_key,
            history_key,
            time.time(),
            generation,
            self._code_digest(email, code),
        )

        if status == 0:
            raise RepositoryError(
                429,
                "인증코드는 60초 간격으로 발송할 수 있습니다.",
                int(retry_after),
            )

        if status == -1:
            raise RepositoryError(
                429,
                "최근 1시간의 인증메일 발송 한도 "
                "5회를 초과했습니다.",
                int(retry_after),
            )

        try:
            self._send_html_email(
                email,
                code,
            )

        except Exception:
            logger.exception(
                "Gmail 인증메일 발송 실패"
            )

            self.redis.eval(
                self.CLEANUP_FAILED_SEND_SCRIPT,
                3,
                code_key,
                cooldown_key,
                history_key,
                generation,
            )

            raise RepositoryError(
                503,
                "인증메일을 발송하지 못했습니다. "
                "재전송을 시도하세요.",
            )

        return {
            "expires_in": max(
                0,
                self.redis.ttl(code_key),
            ),
            "resend_after": max(
                0,
                self.redis.ttl(cooldown_key),
            ),
        }

    def check_code(self, email, code):
        status, remaining = self.redis.eval(
            self.VERIFY_SCRIPT,
            1,
            self._keys(email)[0],
            self._code_digest(email, code),
        )

        if status == -1:
            raise RepositoryError(
                400,
                "인증코드가 없거나 만료되었습니다. "
                "재전송하세요.",
            )

        if status == -2:
            raise RepositoryError(
                429,
                "인증 확인 5회를 초과했습니다. "
                "코드를 재전송하세요.",
            )

        if status == 0:
            if remaining == 0:
                raise RepositoryError(
                    429,
                    "인증코드가 틀렸습니다. "
                    "5회에 도달했으므로 재전송하세요.",
                )

            raise RepositoryError(
                400,
                "인증코드가 틀렸습니다. "
                f"남은 확인 횟수: {remaining}회",
            )

    def delete_code(self, email):
        self.redis.delete(
            self._keys(email)[0]
        )

    def _send_html_email(self, email, code):
        gmail_address = os.environ[
            "GMAIL_ADDRESS"
        ].strip()

        # 복사할 때 포함된 표시용 공백을 제거한다.
        app_password = "".join(
            os.environ[
                "GMAIL_APP_PASSWORD"
            ].split()
        )

        smtp_host = os.environ[
            "SMTP_HOST"
        ].strip()

        smtp_port = int(
            os.environ["SMTP_PORT"]
        )

        if not gmail_address or not app_password:
            raise ValueError(
                "GMAIL_ADDRESS와 GMAIL_APP_PASSWORD를 "
                "설정하세요."
            )

        if smtp_port != 587:
            raise ValueError(
                "현재 코드는 STARTTLS 방식입니다. "
                "SMTP_PORT를 587로 설정하세요."
            )

        message = EmailMessage()

        message["Subject"] = (
            "[추천 시스템] 이메일 인증코드"
        )

        message["From"] = gmail_address
        message["To"] = email

        message.set_content(
            f"인증코드: {code}\n"
            "발급 후 5분 안에 입력하세요."
        )

        message.add_alternative(
            f"""
            <!doctype html>
            <html lang="ko">
              <body style="
                font-family: Arial, sans-serif;
                padding: 24px;
                color: #222;
              ">
                <h2>이메일 인증</h2>

                <p>
                  아래 6자리 코드를 입력하세요.
                </p>

                <div style="
                  font-size: 32px;
                  font-weight: bold;
                  letter-spacing: 8px;
                  padding: 20px;
                  background: #f2f4f8;
                ">
                  {code}
                </div>

                <p>
                  발급 후 5분 동안 유효합니다.
                </p>

                <p>
                  본인이 요청하지 않았다면 무시하세요.
                </p>
              </body>
            </html>
            """,
            subtype="html",
        )

        # 587 포트: SMTP 연결 후 STARTTLS로 암호화한다.
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=15,
        ) as smtp:
            smtp.ehlo()

            smtp.starttls(
                context=ssl.create_default_context()
            )

            smtp.ehlo()

            smtp.login(
                gmail_address,
                app_password,
                initial_response_ok=False,
            )

            smtp.send_message(message)