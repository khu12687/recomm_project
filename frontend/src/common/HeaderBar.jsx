import React from "react";

import {
  Button,
  Layout,
  Space,
  Typography,
} from "antd";

import styled from "styled-components";

import { useAuth } from "../auth/query/auth.jsx";

const StyledHeader = styled(Layout.Header)`
  min-height: 72px;
  height: auto;
  padding: 16px 24px;

  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;

  line-height: normal;
  background: #ffffff;
  border-bottom: 1px solid #e8ecf2;
`;

export default function HeaderBar({
  onLogin,
  onSignup,
}) {
  const {
    user,
    isAuthenticated,
    logout,
  } = useAuth();

  return (
    <StyledHeader>
      <Typography.Title
        level={4}
        style={{ margin: 0 }}
      >
        영화 추천 시스템
      </Typography.Title>

      <Space wrap>
        {isAuthenticated ? (
          <>
            <Typography.Text type="secondary">
              {user?.email || "로그인됨"}
            </Typography.Text>

            <Button onClick={() => logout()}>
              로그아웃
            </Button>
          </>
        ) : (
          <>
            <Button onClick={onLogin}>
              로그인
            </Button>

            <Button
              type="primary"
              onClick={onSignup}
            >
              회원가입
            </Button>
          </>
        )}
      </Space>
    </StyledHeader>
  );
}