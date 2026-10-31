import React from "react";

import {
    Alert,
    Button,
    Form,
    Input,
    Modal,
    Space,
} from "antd";

import { getErrorMessage } from "../api/transformer.js";
import { useLogin } from "../query/transformer.jsx";

function LoginForm({ onClose, onSignup }) {
    const login = useLogin();

    async function submit(values) {
        try {
            await login.mutateAsync({
                email: values.email
                    .trim()
                    .toLowerCase(),
                password: values.password,
            });

            onClose();
        } catch {
            // 서버 오류는 Alert로 표시.
        }
    }

    return (
        <Form
            layout="vertical"
            preserve={false}
            onFinish={submit}
        >
            {login.error && (
                <Alert
                    type="error"
                    showIcon
                    message={getErrorMessage(login.error)}
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
                ]}
            >
                <Input.Password
                    autoComplete="current-password"
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
                    loading={login.isPending}
                >
                    로그인
                </Button>

                <Button
                    block
                    type="link"
                    disabled={login.isPending}
                    onClick={onSignup}
                >
                    회원가입 / 이메일 인증
                </Button>
            </Space>
        </Form>
    );
}

export default function LoginModal({
                                       open,
                                       onClose,
                                       onSignup,
                                   }) {
    return (
        <Modal
            title="로그인"
            open={open}
            onCancel={onClose}
            footer={null}
            destroyOnHidden
        >
            <LoginForm
                onClose={onClose}
                onSignup={onSignup}
            />
        </Modal>
    );
}