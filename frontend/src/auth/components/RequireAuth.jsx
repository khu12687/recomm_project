import React from "react";

import {
  Alert,
  Button,
  Spin,
} from "antd";

import {
  Navigate,
  Outlet,
} from "react-router-dom";

import { useAuth } from "../query/auth.jsx";

import {
  getErrorMessage,
} from "../../common/api.js";

export default function RequireAuth() {
  const {
    isAuthenticated,
    isLoading,
    user,
    error,
    refetch,
  } = useAuth();

  if (!isAuthenticated) {
    return (
      <Navigate
        to="/member"
        replace
        state={{ openLogin: true }}
      />
    );
  }

  if (isLoading) {
    return (
      <div style={{ padding: 40 }}>
        <Spin tip="로그인 확인 중...">
          <div style={{ minHeight: 100 }} />
        </Spin>
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={getErrorMessage(error)}
        action={
          <Button onClick={() => refetch()}>
            다시 확인
          </Button>
        }
      />
    );
  }

  if (!user) {
    return (
      <Navigate
        to="/member"
        replace
        state={{ openLogin: true }}
      />
    );
  }

  return <Outlet />;
}