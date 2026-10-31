import { useQuery } from "@tanstack/react-query";

import {
    getKpi,
    getRecommendations,
} from "../api/mf.js";

export function useMfKpi() {
    return useQuery({
        queryKey: ["mf", "kpi"],
        queryFn: getKpi,
        retry: false,
        staleTime: 60000,
    });
}

export function useMfRecommendations(userId) {
    return useQuery({
        queryKey: [
            "mf",
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