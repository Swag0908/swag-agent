package com.swag.tool;

import tools.jackson.databind.JsonNode;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;

/**
 * 联网搜索工具：调用 Tavily Search API，让大模型获取最新/实时/事实性信息。
 */
@Component
public class WebSearchTools {

    private final RestClient restClient;

    @Value("${web.search.tavily.api-key:}")
    private String apiKey;

    public WebSearchTools(RestClient.Builder builder) {
        this.restClient = builder.baseUrl("https://api.tavily.com").build();
    }

    @Tool(description = "联网搜索互联网上的最新、实时或事实性信息，返回结果摘要与来源链接。"
            + "当用户的问题需要上网查询、涉及时效性内容（新闻/天气/最新数据/最新政策），"
            + "或模型对答案不确定时，先调用本工具再基于结果回答。")
    public String webSearch(@ToolParam(description = "搜索关键词或完整问题") String query) {
        if (apiKey == null || apiKey.isBlank()) {
            return "未配置 Tavily API Key（web.search.tavily.api-key），无法联网搜索。";
        }
        try {
            JsonNode resp = restClient.post()
                    .uri("/search")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "api_key", apiKey,
                            "query", query,
                            "search_depth", "basic",
                            "max_results", 5))
                    .retrieve()
                    .body(JsonNode.class);

            StringBuilder sb = new StringBuilder();
            if (resp != null && resp.hasNonNull("answer") && !resp.path("answer").asText().isBlank()) {
                sb.append("回答：").append(resp.path("answer").asText()).append("\n\n");
            }
            if (resp != null) {
                for (JsonNode r : resp.path("results")) {
                    sb.append("• ").append(r.path("title").asText()).append("\n")
                            .append("  链接：").append(r.path("url").asText()).append("\n")
                            .append("  摘要：").append(r.path("content").asText()).append("\n\n");
                }
            }
            String result = sb.toString().trim();
            return result.isEmpty() ? "搜索无结果。" : result;
        } catch (Exception e) {
            return "搜索失败：" + e.getMessage();
        }
    }
}
