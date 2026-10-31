import React from "react";

import RecommendationPage from
  "../../common/RecommendationPage.jsx";

export default function SvdPage() {
  return (
    <RecommendationPage
      model="svd"
      title="SVD 영화 추천"
      description="희소 행렬을 분해해 고객이 아직 평가하지 않은 영화의 평점을 예측합니다."
    />
  );
}