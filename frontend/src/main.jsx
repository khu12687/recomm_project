import "@ant-design/v5-patch-for-react-19";

import React from "react";
import ReactDOM from "react-dom/client";

import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

import { ConfigProvider } from "antd";
import koKR from "antd/locale/ko_KR";

import { BrowserRouter } from "react-router-dom";

import "antd/dist/reset.css";
import "./styles.css";

import App from "./App.jsx";

import {
  AuthProvider,
} from "./auth/query/auth.jsx";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
    mutations: {
      retry: false,
    },
  },
});

ReactDOM.createRoot(
  document.getElementById("root"),
).render(
  <React.StrictMode>
    <ConfigProvider
      locale={koKR}
      theme={{
        token: {
          colorPrimary: "#315efb",
          borderRadius: 10,
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>,
);