import axios from "axios";

const api = axios.create({
    baseURL: "/api/",
    timeout: 120000,
});

export function getTransformerError(error) {
    const detail = error?.response?.data?.detail;

    if (typeof detail === "string") {
        return detail;
    }

    if (Array.isArray(detail)) {
        return detail
            .map((item) => item.msg)
            .join("\n");
    }

    return error?.response
        ? "Transformer 요청을 처리하지 못했습니다."
        : "서버에 연결하지 못했거나 응답 시간이 초과됐습니다.";
}

export async function getKpi({ signal }) {
    const response = await api.get(
        "transformer/kpi",
        { signal },
    );

    return response.data;
}

export async function getRecommendations({
                                             userId,
                                             signal,
                                         }) {
    const response = await api.get(
        "transformer/recommendations",
        {
            params: {
                user_id: userId,
            },
            signal,
        },
    );

    return response.data;
}