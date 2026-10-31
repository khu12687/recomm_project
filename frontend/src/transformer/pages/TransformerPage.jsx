import React from "react";

import RecommendationPage from
  "../../common/RecommendationPage.jsx";

export default function TransformerPage() {
  return (
    <RecommendationPage
      model="transformer"
      title="Transformer 영화 추천"
      description="시간순 영화·평점 이력을 참고해 다음 영화의 평점을 예측합니다."
    />
  );
}