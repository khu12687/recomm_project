import axios from "axios";

const api = axios.create({
    baseURL: "/api/",
    timeout: 30000,
});

export function getSvdError(error) {
    const detail =
        error.response?.data?.detail;

    if (typeof detail === "string") {
        return detail;
    }

    if (Array.isArray(detail)) {
        return detail
            .map((item) => item.msg)
            .join("\n");
    }

    return error.response
        ? "SVD 요청을 처리하지 못했습니다."
        : "서버에 연결할 수 없습니다.";
}

export async function getKpi({ signal }) {
    const response = await api.get(
        "svd/kpi",
        { signal },
    );

    return response.data;
}

export async function getRecommendations({
                                             userId,
                                             signal,
                                         }) {
    const response = await api.get(
        "svd/recommendations",
        {
            params: {
                user_id: userId,
            },
            signal,
        },
    );

    return response.data;
}