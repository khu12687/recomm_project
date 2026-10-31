import {
    useQuery,
} from "@tanstack/react-query";

import {
    getKpi,
    getRecommendations,
} from "../api/svd";


export function useSvdKpi() {
    return useQuery({
        queryKey: ["svd", "kpi"],
        queryFn: getKpi,
        retry: false,
        staleTime: 60000,
    });
}


export function useSvdRecommendations(userId) {
    return useQuery({
        queryKey: [
            "svd",
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