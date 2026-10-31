import React, { useState } from "react";

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  InputNumber,
  Row,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";

import { useQuery } from "@tanstack/react-query";

import {
  getErrorMessage,
  getModelKpi,
  getModelRecommendations,
} from "./api.js";

const columns = [
  {
    title: "순위",
    dataIndex: "rank",
    width: 80,
  },
  {
    title: "영화 ID",
    dataIndex: "movie_id",
    width: 110,
  },
  {
    title: "영화 제목",
    dataIndex: "title",
  },
  {
    title: "장르",
    dataIndex: "genres",
  },
  {
    title: "예측 평점",
    dataIndex: "predicted_rating",
    width: 130,
    render: (value) =>
      Number(value).toFixed(3),
  },
];

export default function RecommendationPage({
  model,
  title,
  description,
}) {
  const [userId, setUserId] = useState(null);

  const kpi = useQuery({
    queryKey: [model, "kpi"],

    queryFn: ({ signal }) =>
      getModelKpi(model, { signal }),

    retry: false,
    staleTime: 60000,
  });

  const recommendations = useQuery({
    queryKey: [
      model,
      "recommendations",
      userId,
    ],

    queryFn: ({ signal }) =>
      getModelRecommendations(
        model,
        userId,
        { signal },
      ),

    enabled: userId !== null,
    retry: false,
    staleTime: 60000,
  });

  function submit(values) {
    const nextUserId = values.userId;

    if (nextUserId === userId) {
      recommendations.refetch();
    } else {
      setUserId(nextUserId);
    }
  }

  const rows = [
    ...(recommendations.data ?? []),
  ].sort((a, b) => a.rank - b.rank);

  return (
    <Space
      direction="vertical"
      size="large"
      style={{ width: "100%" }}
    >
      <div>
        <Typography.Title level={2}>
          {title}
        </Typography.Title>

        <Typography.Text type="secondary">
          {description}
        </Typography.Text>
      </div>

      {kpi.error && (
        <Alert
          type="error"
          showIcon
          message={getErrorMessage(kpi.error)}
          action={
            <Button
              loading={kpi.isFetching}
              onClick={() => kpi.refetch()}
            >
              다시 조회
            </Button>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        {[
          ["MAE", "mae"],
          ["MSE", "mse"],
          ["RMSE", "rmse"],
        ].map(([label, key]) => (
          <Col
            key={key}
            xs={24}
            sm={8}
          >
            <Card loading={kpi.isPending}>
              {kpi.data ? (
                <Statistic
                  title={label}
                  value={kpi.data[key]}
                  precision={4}
                />
              ) : (
                <Typography.Text>
                  {label}: 조회되지 않음
                </Typography.Text>
              )}
            </Card>
          </Col>
        ))}
      </Row>

      {kpi.data && (
        <Typography.Text type="secondary">
          검증 평점:{" "}
          {kpi.data.validation_count.toLocaleString()}
          건

          {kpi.data.device && (
            <>
              {" · "}
              학습 장치: {kpi.data.device}
            </>
          )}

          {kpi.data.best_epoch != null && (
            <>
              {" · "}
              선택 Epoch: {kpi.data.best_epoch}
            </>
          )}
        </Typography.Text>
      )}

      <Card title="고객별 추천 영화">
        <Form
          layout="inline"
          onFinish={submit}
          style={{
            gap: 12,
            marginBottom: 24,
          }}
        >
          <Form.Item
            name="userId"
            label="고객 ID"
            rules={[
              {
                required: true,
                message: "고객 ID를 입력하세요.",
              },
              {
                validator(_, value) {
                  if (
                    value == null ||
                    (
                      Number.isSafeInteger(value) &&
                      value > 0
                    )
                  ) {
                    return Promise.resolve();
                  }

                  return Promise.reject(
                    new Error(
                      "양의 정수를 입력하세요.",
                    ),
                  );
                },
              },
            ]}
          >
            <InputNumber
              min={1}
              precision={0}
              placeholder="예: 1"
              style={{ width: 180 }}
            />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={recommendations.isFetching}
            >
              영화 5편 추천
            </Button>
          </Form.Item>
        </Form>

        <Typography.Paragraph type="secondary">
          회원가입 번호가 아니라 영화 평점 데이터의
          고객 ID를 입력하세요.
        </Typography.Paragraph>

        {recommendations.error && (
          <Alert
            type="error"
            showIcon
            message={getErrorMessage(
              recommendations.error,
            )}
            style={{ marginBottom: 20 }}
          />
        )}

        {userId === null ? (
          <Empty description="고객 ID를 입력하세요." />
        ) : (
          <>
            <Typography.Paragraph>
              고객 {userId}번의 추천 결과
            </Typography.Paragraph>

            <Table
              rowKey="movie_id"
              columns={columns}
              dataSource={rows}
              loading={recommendations.isFetching}
              pagination={false}
              scroll={{ x: 750 }}
              locale={{
                emptyText: recommendations.error
                  ? "추천 결과를 조회하지 못했습니다."
                  : "추천할 미평가 영화가 없습니다.",
              }}
            />
          </>
        )}
      </Card>
    </Space>
  );
}