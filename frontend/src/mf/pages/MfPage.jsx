import React from "react";

import RecommendationPage from
  "../../common/RecommendationPage.jsx";

export default function MfPage() {
  return (
    <RecommendationPage
      model="mf"
      title="MF 영화 추천"
      description="고객 벡터와 영화 벡터의 내적으로 평점을 예측합니다."
    />
  );
}