import React from "react";

import {
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import AppLayout from "./common/AppLayout.jsx";

import RequireAuth from
  "./auth/components/RequireAuth.jsx";

import MemberPage from
  "./auth/pages/MemberPage.jsx";

import SvdPage from
  "./svd/pages/SvdPage.jsx";

import MfPage from
  "./mf/pages/MfPage.jsx";

import TransformerPage from
  "./transformer/pages/TransformerPage.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route
          index
          element={
            <Navigate to="/member" replace />
          }
        />

        <Route
          path="/member"
          element={<MemberPage />}
        />

        <Route element={<RequireAuth />}>
          <Route
            path="/svd"
            element={<SvdPage />}
          />

          <Route
            path="/mf"
            element={<MfPage />}
          />

          <Route
            path="/transformer"
            element={<TransformerPage />}
          />
        </Route>

        <Route
          path="*"
          element={
            <Navigate to="/member" replace />
          }
        />
      </Route>
    </Routes>
  );
}