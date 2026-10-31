import React, {
    useEffect,
    useState,
} from "react";

import {
    Alert,
    Button,
    Form,
    Input,
    Modal,
    Space,
    Typography,
} from "antd";

import { getErrorMessage } from "../api/transformer.js";

import {
    useResendCode,
    useSignup,
    useVerifyEmail,
} from "../query/transformer.jsx";

function formatTime(seconds) {
    const value = Math.max(0, seconds);

    const minutes = String(
        Math.floor(value / 60),
    ).padStart(2, "0");

    const remainder = String(
        value % 60,
    ).padStart(2, "0");

    return `${minutes}:${remainder}`;
}

function toTiming(response) {
    const receivedAt = Date.now();

    const serverNow = Date.parse(
        response.server_time,
    );

    const expiresAt = Date.parse(
        response.expires_at,
    );

    const resendAt = Date.parse(
        response.resend_available_at,
    );

    if (
        ![serverNow, expiresAt, resendAt].every(
            Number.isFinite,
        )
    ) {
        throw new Error(
            "서버의 인증시간 응답이 올바르지 않습니다.",
        );
    }

    return {
        expiresAt:
            receivedAt +
            Math.max(0, expiresAt - serverNow),

        resendAt:
            receivedAt +
            Math.max(0, resendAt - serverNow),
    };
}

function VerificationForm({
                              email,
                              initialResponse,
                              onLogin,
                          }) {
    const [form] = Form.useForm();

    const verify = useVerifyEmail();
    const resend = useResendCode();

    const [timing, setTiming] = useState(() =>
        initialResponse
            ? toTiming(initialResponse)
            : null,
    );

    const [now, setNow] = useState(Date.now());
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    const [verified, setVerified] = useState(false);

    const [attemptsBlocked, setAttemptsBlocked] =
        useState(false);

    useEffect(() => {
        const timer = setInterval(() => {
            setNow(Date.now());
        }, 250);

        return () => clearInterval(timer);
    }, []);

    const secondsLeft = timing
        ? Math.max(
            0,
            Math.ceil(
                (timing.expiresAt - now) / 1000,
            ),
        )
        : 0;

    const resendWait = timing
        ? Math.max(
            0,
            Math.ceil(
                (timing.resendAt - now) / 1000,
            ),
        )
        : 0;

    const busy =
        verify.isPending || resend.isPending;

    async function submit(values) {
        setError("");
        setMessage("");

        if (
            secondsLeft <= 0 ||
            attemptsBlocked
        ) {
            setError(
                "새 인증코드를 발송한 뒤 다시 인증하세요.",
            );
            return;
        }

        try {
            const response =
                await verify.mutateAsync({
                    email,
                    code: values.code,
                });

            setVerified(true);
            setMessage(response.message);
        } catch (requestError) {
            setError(
                getErrorMessage(requestError),
            );

            if (
                requestError.response?.status === 429
            ) {
                setAttemptsBlocked(true);
            }
        }
    }

    async function sendAgain() {
        setError("");
        setMessage("");

        try {
            const response =
                await resend.mutateAsync({ email });

            setTiming(toTiming(response));
            setNow(Date.now());
            setAttemptsBlocked(false);
            setMessage(response.message);

            form.resetFields();
        } catch (requestError) {
            setError(
                requestError.response
                    ? getErrorMessage(requestError)
                    : requestError.message ||
                    getErrorMessage(requestError),
            );

            const retryAfter = Number(
                requestError.response?.headers?.[
                    "retry-after"
                    ],
            );

            if (
                Number.isFinite(retryAfter) &&
                retryAfter > 0
            ) {
                const currentTime = Date.now();

                setTiming((previous) => ({
                    expiresAt:
                        previous?.expiresAt ??
                        currentTime,

                    resendAt:
                        currentTime + retryAfter * 1000,
                }));

                setNow(currentTime);
            }
        }
    }

    return (
        <Space
            direction="vertical"
            size="middle"
            style={{ width: "100%" }}
        >
            <Typography.Text>
                인증 이메일: <strong>{email}</strong>
            </Typography.Text>

            {error && (
                <Alert
                    showIcon
                    type="error"
                    message={error}
                />
            )}

            {message && (
                <Alert
                    showIcon
                    type="success"
                    message={message}
                />
            )}

            {verified ? (
                <Button
                    block
                    type="primary"
                    onClick={onLogin}
                >
                    로그인하러 가기
                </Button>
            ) : (
                <>
                    {!timing && (
                        <Alert
                            showIcon
                            type="info"
                            message="인증코드를 다시 보내고 메일을 확인하세요."
                        />
                    )}

                    <div className="verification-timer">
                        <Typography.Text type="secondary">
                            남은 인증시간
                        </Typography.Text>

                        <div
                            role="timer"
                            className={
                                secondsLeft > 0
                                    ? "timer-value"
                                    : "timer-value expired"
                            }
                        >
                            {timing
                                ? formatTime(secondsLeft)
                                : "--:--"}
                        </div>
                    </div>

                    <Form
                        form={form}
                        layout="vertical"
                        preserve={false}
                        onFinish={submit}
                    >
                        <Form.Item
                            name="code"
                            label="6자리 인증코드"
                            rules={[
                                {
                                    required: true,
                                    message:
                                        "인증코드를 입력하세요.",
                                },
                                {
                                    pattern: /^[0-9]{6}$/,
                                    message:
                                        "숫자 6자리를 입력하세요.",
                                },
                            ]}
                        >
                            <Input
                                maxLength={6}
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                placeholder="예: 012345"
                                disabled={
                                    busy ||
                                    secondsLeft === 0 ||
                                    attemptsBlocked
                                }
                            />
                        </Form.Item>

                        <Button
                            block
                            type="primary"
                            htmlType="submit"
                            loading={verify.isPending}
                            disabled={
                                resend.isPending ||
                                secondsLeft === 0 ||
                                attemptsBlocked
                            }
                        >
                            인증 확인
                        </Button>
                    </Form>

                    {timing && secondsLeft === 0 && (
                        <Typography.Text type="danger">
                            인증시간이 끝났습니다.
                            코드를 다시 보내세요.
                        </Typography.Text>
                    )}

                    <Button
                        block
                        onClick={sendAgain}
                        loading={resend.isPending}
                        disabled={
                            verify.isPending ||
                            resendWait > 0
                        }
                    >
                        {resendWait > 0
                            ? `다시 보내기까지 ${formatTime(resendWait)}`
                            : "인증코드 다시 보내기"}
                    </Button>
                </>
            )}
        </Space>
    );
}

function SignupForm({ onLogin }) {
    const [form] = Form.useForm();
    const signup = useSignup();

    const [verification, setVerification] =
        useState(null);

    const [localError, setLocalError] =
        useState("");

    async function submit(values) {
        setLocalError("");

        const email = values.email
            .trim()
            .toLowerCase();

        try {
            const response =
                await signup.mutateAsync({
                    email,
                    password: values.password,
                });

            // 인증 화면을 열기 전에 시간 응답 검증.
            toTiming(response);

            setVerification({
                email,
                response,
            });
        } catch (error) {
            if (!error.response) {
                setLocalError(
                    error.message ||
                    getErrorMessage(error),
                );
            }
        }
    }

    async function resumeVerification() {
        try {
            const values =
                await form.validateFields(["email"]);

            setVerification({
                email: values.email
                    .trim()
                    .toLowerCase(),
                response: null,
            });
        } catch {
            // 입력 오류는 Form에 표시.
        }
    }

    if (verification) {
        return (
            <VerificationForm
                email={verification.email}
                initialResponse={
                    verification.response
                }
                onLogin={onLogin}
            />
        );
    }

    const errorMessage = localError ||
        (signup.error
            ? getErrorMessage(signup.error)
            : "");

    return (
        <Form
            form={form}
            layout="vertical"
            preserve={false}
            onFinish={submit}
        >
            {errorMessage && (
                <Alert
                    showIcon
                    type="error"
                    message={errorMessage}
                    style={{ marginBottom: 20 }}
                />
            )}

            <Form.Item
                name="email"
                label="이메일"
                rules={[
                    {
                        required: true,
                        message: "이메일을 입력하세요.",
                    },
                    {
                        type: "email",
                        message:
                            "이메일 형식을 확인하세요.",
                    },
                ]}
            >
                <Input
                    autoComplete="username"
                    placeholder="you@example.com"
                />
            </Form.Item>

            <Form.Item
                name="password"
                label="비밀번호"
                rules={[
                    {
                        required: true,
                        message:
                            "비밀번호를 입력하세요.",
                    },
                    {
                        min: 8,
                        max: 128,
                        message:
                            "8~128자로 입력하세요.",
                    },
                ]}
            >
                <Input.Password
                    autoComplete="new-password"
                    maxLength={128}
                />
            </Form.Item>

            <Form.Item
                name="confirmPassword"
                label="비밀번호 확인"
                dependencies={["password"]}
                rules={[
                    {
                        required: true,
                        message:
                            "비밀번호를 다시 입력하세요.",
                    },

                    ({ getFieldValue }) => ({
                        validator(_, value) {
                            if (
                                !value ||
                                value ===
                                getFieldValue("password")
                            ) {
                                return Promise.resolve();
                            }

                            return Promise.reject(
                                new Error(
                                    "비밀번호가 일치하지 않습니다.",
                                ),
                            );
                        },
                    }),
                ]}
            >
                <Input.Password
                    autoComplete="new-password"
                    maxLength={128}
                />
            </Form.Item>

            <Space
                direction="vertical"
                style={{ width: "100%" }}
            >
                <Button
                    block
                    type="primary"
                    htmlType="submit"
                    loading={signup.isPending}
                >
                    회원가입 및 인증메일 발송
                </Button>

                <Button
                    block
                    onClick={resumeVerification}
                    disabled={signup.isPending}
                >
                    기존 계정 이메일 인증
                </Button>

                <Button
                    block
                    type="link"
                    onClick={onLogin}
                    disabled={signup.isPending}
                >
                    이미 인증했다면 로그인
                </Button>
            </Space>
        </Form>
    );
}

export default function SignupModal({
                                        open,
                                        onClose,
                                        onLogin,
                                    }) {
    return (
        <Modal
            title="회원가입 · 이메일 인증"
            open={open}
            onCancel={onClose}
            footer={null}
            destroyOnHidden
            maskClosable={false}
        >
            <SignupForm onLogin={onLogin} />
        </Modal>
    );
}