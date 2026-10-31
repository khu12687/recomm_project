import React from "react";

import { Layout, Menu } from "antd";

import {
  useLocation,
  useNavigate,
} from "react-router-dom";

import styled from "styled-components";

const StyledSider = styled(Layout.Sider)`
  background: #ffffff !important;
  border-right: 1px solid #e8ecf2;
`;

const StyledMenu = styled(Menu)`
  padding-top: 20px;
  border-inline-end: none !important;
`;

export default function SideBar() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <StyledSider
      width={220}
      breakpoint="lg"
      collapsedWidth={0}
    >
      <StyledMenu
        mode="inline"
        selectedKeys={[location.pathname]}
        onClick={({ key }) => navigate(key)}
        items={[
          {
            key: "/member",
            label: "회원",
          },
          {
            key: "/svd",
            label: "SVD 추천",
          },
          {
            key: "/mf",
            label: "MF 추천",
          },
          {
            key: "/transformer",
            label: "Transformer 추천",
          },
        ]}
      />
    </StyledSider>
  );
}