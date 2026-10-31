# 영화 추천 시스템 실습

React·FastAPI·PostgreSQL을 연결하고, SVD·MF·Transformer의 추천 결과를 웹 화면으로 제공하는 프로젝트입니다.

학습 정리: **2026년 10월 31일**

## 1. 오늘의 목표

- 회원가입·이메일 인증·로그인 구현
- 영화와 평점을 긴 표로 PostgreSQL에 저장
- SVD·MF·Transformer를 각각 학습하고 체크포인트 저장
- 검증 평점의 MAE·MSE·RMSE 표시
- 고객별 미평가 영화 최대 5편 추천
- 로그인한 회원만 추천 화면과 API에 접근하도록 제한
- 기존 DB와 학습 모델을 유지하면서 Docker Compose로 배포

```text
회원가입 → 이메일 인증 → 로그인 → JWT 발급
→ 고객 ID 선택 → 추천 API → 저장 모델로 예측
→ 이미 평가한 영화 제외 → 추천 5편 표시
```

> 회원가입으로 생성된 회원 ID와 영화 평점 데이터의 고객 ID는 별개입니다. 현재 화면은 로그인한 회원이 데이터셋의 고객 ID를 선택하는 실습 구조이며, 회원의 실제 취향 이력을 자동 연결한 구조는 아닙니다.

## 2. 기술 구성

| 영역 | 사용 기술 |
|---|---|
| 프론트 | Vite, React, JavaScript |
| 화면 | Ant Design, styled-components, React Router |
| 서버 통신 | Axios, TanStack Query |
| 백엔드 | Python 3.13, FastAPI, Uvicorn, Pydantic |
| DB 접근 | SQLAlchemy, Psycopg |
| 데이터 저장 | PostgreSQL 17 |
| 임시 인증 정보 | Redis |
| 인증 | Argon2 비밀번호 해시, JWT, Gmail SMTP |
| 모델 | NumPy, SciPy, PyTorch |
| 배포 | Docker Compose, Nginx |

TypeScript와 프론트 `.env`는 사용하지 않습니다.

## 3. 프로젝트 구조

```text
recomm_project/
├── .env
├── .gitignore
├── .dockerignore
├── docker-compose.yml
├── nginx/
│   ├── Dockerfile
│   └── default.conf.template
├── backend/
│   ├── .venv/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── load_data.py
│   ├── checkpoint/
│   │   ├── svd.pkl
│   │   ├── mf.pt
│   │   └── transformer.pt
│   └── app/
│       ├── main.py
│       ├── data/
│       │   ├── ratings.pkl
│       │   └── movies.dat
│       ├── auth/
│       ├── svd/
│       ├── mf/
│       └── transformer/
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── common/
        │   ├── api.js
        │   ├── HeaderBar.jsx
        │   ├── SideBar.jsx
        │   ├── AppLayout.jsx
        │   └── RecommendationPage.jsx
        ├── auth/
        ├── svd/
        ├── mf/
        └── transformer/
```

각 백엔드 모듈은 `model.py`, `schema.py`, `repository.py`, `service.py`, `web.py`로 역할을 나눕니다.

| 구성 | 역할 |
|---|---|
| web | HTTP 요청 수신·검증·응답 |
| service | 회원 규칙 또는 모델 학습·평가·추천 |