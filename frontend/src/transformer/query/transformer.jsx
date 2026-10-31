import { useQuery } from "@tanstack/react-query";

import {
    getKpi,
    getRecommendations,
} from "../api/transformer.js";

export function useTransformerKpi() {
    return useQuery({
        queryKey: ["transformer", "kpi"],
        queryFn: getKpi,
        retry: false,
        staleTime: 60000,
    });
}

export function useTransformerRecommendations(userId) {
    return useQuery({
        queryKey: [
            "transformer",
            "recommendations",
            userId,
        ],

        queryFn: ({ signal }) =>
            getRecommendations({
                userId,
                signal,
            }),

        enabled: userId !== null,
        retry: false,
        staleTime: 60000,
    });
}