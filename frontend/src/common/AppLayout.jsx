import React, {
  useEffect,
  useState,
} from "react";

import { Layout } from "antd";

import {
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";

import styled from "styled-components";

import HeaderBar from "./HeaderBar.jsx";
import SideBar from "./SideBar.jsx";

import LoginModal from
  "../auth/components/LoginModal.jsx";

import SignupModal from
  "../auth/components/SignUpmodal.jsx";

import {
  useAuth,
} from "../auth/query/auth.jsx";

const RootLayout = styled(Layout)`
  min-height: 100vh;
`;

const MainContent = styled(Layout.Content)`
  min-width: 0;
  padding: 32px;
  background: #f4f6fa;

  @media (max-width: 640px) {
    padding: 16px;
  }
`;

export default function AppLayout() {
  const [modal, setModal] = useState(null);

  const location = useLocation();
  const navigate = useNavigate();

  const { isAuthenticated } = useAuth();

  const openLogin = () => setModal("login");
  const openSignup = () => setModal("signup");
  const closeModal = () => setModal(null);

  useEffect(() => {
    if (!location.state?.openLogin) {
      return;
    }

    if (!isAuthenticated) {
      setModal("login");
    }

    // 새로고침 때 이전 모달 요청이 반복되지 않도록 제거.
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
      {
        replace: true,
        state: null,
      },
    );
  }, [
    location,
    navigate,
    isAuthenticated,
  ]);

  return (
    <RootLayout>
      <HeaderBar
        onLogin={openLogin}
        onSignup={openSignup}
      />

      <Layout>
        <SideBar />

        <MainContent>
          <Outlet
            context={{
              openLogin,
              openSignup,
            }}
          />
        </MainContent>
      </Layout>

      <LoginModal
        open={modal === "login"}
        onClose={closeModal}
        onSignup={openSignup}
      />

      <SignupModal
        open={modal === "signup"}
        onClose={closeModal}
        onLogin={openLogin}
      />
    </RootLayout>
  );
}