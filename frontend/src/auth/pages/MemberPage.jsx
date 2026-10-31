import React from "react";

import {
    Alert,
    Button,
    Card,
    Descriptions,
    Space,
    Spin,
    Tag,
    Typography,
} from "antd";

import { useOutletContext } from "react-router-dom";

import { getErrorMessage } from "../api/auth";
import { useAuth } from "../query/auth";

export default function MemberPage() {
    const {
        user,
        isAuthenticated,
        isLoading,
        error,
        refetch,
        notice,
    } = useAuth();

    const {
        openLogin,
        openSignup,
    } = useOutletContext();

    return (
        <Space
            direction="vertical"
            size="large"
            style={{
                width: "100%",
                maxWidth: 900,
            }}
        >
            <div>
                <Typography.Title level={2}>
                    회원
                </Typography.Title>

                <Typography.Text type="secondary">
                    회원가입과 이메일 인증 후
                    로그인할 수 있습니다.
                </Typography.Text>
            </div>

            {notice && (
                <Alert
                    showIcon
                    type="warning"
                    message={notice}
                />
            )}

            {!isAuthenticated ? (
                <Card title="회원 서비스">
                    <Typography.Paragraph>
                        이메일로 받은 6자리 인증코드로
                        가입을 완료하세요.
                    </Typography.Paragraph>

                    <Space wrap>
                        <Button
                            type="primary"
                            onClick={openSignup}
                        >
                            회원가입 / 이메일 인증
                        </Button>

                        <Button onClick={openLogin}>
                            로그인
                        </Button>
                    </Space>
                </Card>
            ) : (
                <Card title="내 정보">
                    {isLoading && <Spin />}

                    {error && (
                        <Space
                            direction="vertical"
                            style={{ width: "100%" }}
                        >
                            <Alert
                                showIcon
                                type="error"
                                message={getErrorMessage(error)}
                            />

                            <Button
                                onClick={() => refetch()}
                            >
                                다시 조회
                            </Button>
                        </Space>
                    )}

                    {!error && user && (
                        <Descriptions
                            bordered
                            column={1}
                        >
                            <Descriptions.Item label="회원 ID">
                                {user.id}
                            </Descriptions.Item>

                            <Descriptions.Item label="이메일">
                                {user.email}
                            </Descriptions.Item>

                            <Descriptions.Item label="이메일 인증">
                                <Tag
                                    color={
                                        user.is_verified
                                            ? "green"
                                            : "orange"
                                    }
                                >
                                    {user.is_verified
                                        ? "인증 완료"
                                        : "미인증"}
                                </Tag>
                            </Descriptions.Item>

                            <Descriptions.Item label="가입일">
                                {new Date(
                                    user.created_at,
                                ).toLocaleString("ko-KR")}
                            </Descriptions.Item>
                        </Descriptions>
                    )}
                </Card>
            )}
        </Space>
    );
}