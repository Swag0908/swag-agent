package com.swag.audit.query;

import com.swag.auth.AppUserDO;
import com.swag.auth.AuthService;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 把审计事件还原成「一次请求一条」的调用链汇总，供管理端列表展示。
 *
 * <p>一次请求可能产生几十条事件（AGENT_*、TOOL_CALL_*、CONFIRMATION_*…），
 * 列表里只需要请求级的三类：REQUEST_RECEIVED（谁、请求了什么）、
 * REQUEST_COMPLETED / REQUEST_FAILED（最终状态、HTTP 码）。
 */
@Service
public class AuditChainQueryService {

    public static final int DEFAULT_LIMIT = 30;
    public static final int MAX_LIMIT = 200;

    private static final String REQUEST_RECEIVED = "REQUEST_RECEIVED";

    private final JdbcAuditQueryRepository repository;
    private final ZipkinTraceLinkBuilder zipkinTraceLinkBuilder;
    private final AuthService authService;
    private final ObjectMapper objectMapper;

    public AuditChainQueryService(JdbcAuditQueryRepository repository,
                                  ZipkinTraceLinkBuilder zipkinTraceLinkBuilder,
                                  AuthService authService,
                                  ObjectMapper objectMapper) {
        this.repository = repository;
        this.zipkinTraceLinkBuilder = zipkinTraceLinkBuilder;
        this.authService = authService;
        this.objectMapper = objectMapper;
    }

    public List<AuditChainView> recentChains(int limit) {
        int size = Math.max(1, Math.min(limit, MAX_LIMIT));
        List<JdbcAuditQueryRepository.ChainSummary> chains = repository.findRecentChains(size);
        if (chains.isEmpty()) {
            return List.of();
        }

        Map<UUID, List<JdbcAuditQueryRepository.RequestEvent>> eventsByChain = repository
                .findRequestEvents(chains.stream()
                        .map(JdbcAuditQueryRepository.ChainSummary::auditId)
                        .toList())
                .stream()
                .collect(Collectors.groupingBy(
                        JdbcAuditQueryRepository.RequestEvent::auditId,
                        LinkedHashMap::new,
                        Collectors.toList()));

        // 一次拉全量用户建映射，避免每行都回查一次用户表
        Map<String, String> userNames = userNames();

        return chains.stream()
                .map(chain -> toView(chain,
                        eventsByChain.getOrDefault(chain.auditId(), List.of()),
                        userNames))
                .toList();
    }

    private Map<String, String> userNames() {
        try {
            return authService.listUsers().stream()
                    .collect(Collectors.toMap(
                            user -> String.valueOf(user.getId()),
                            AppUserDO::getUsername,
                            (first, second) -> first));
        }
        catch (RuntimeException ignored) {
            // 用户名只是锦上添花，查不到就退回显示 actorId
            return Map.of();
        }
    }

    private AuditChainView toView(JdbcAuditQueryRepository.ChainSummary chain,
                                  List<JdbcAuditQueryRepository.RequestEvent> events,
                                  Map<String, String> userNames) {
        JdbcAuditQueryRepository.RequestEvent received = events.stream()
                .filter(event -> REQUEST_RECEIVED.equals(event.eventType()))
                .findFirst()
                .orElse(null);
        JdbcAuditQueryRepository.RequestEvent finished = events.stream()
                .filter(event -> !REQUEST_RECEIVED.equals(event.eventType()))
                .reduce((first, second) -> second)
                .orElse(null);

        Map<String, Object> receivedData = eventData(received);
        Map<String, Object> finishedData = eventData(finished);

        String traceId = events.stream()
                .map(JdbcAuditQueryRepository.RequestEvent::traceId)
                .filter(value -> value != null && !value.isBlank())
                .findFirst()
                .orElse(null);

        String status = finished != null
                ? finished.executionStatus()
                : received != null ? "IN_PROGRESS" : "UNKNOWN";

        String actorId = received == null ? null : received.actorId();

        return new AuditChainView(
                chain.auditId(),
                chain.startedAt(),
                chain.endedAt(),
                chain.eventCount(),
                actorId,
                actorId == null ? null : userNames.getOrDefault(actorId, actorId),
                text(receivedData.get("method")),
                text(receivedData.get("path")),
                number(finishedData.get("httpStatus")),
                status,
                traceId,
                traceId == null ? null : zipkinTraceLinkBuilder.build(traceId));
    }

    /** event_data 是历史遗留的自由 JSON，解析失败一律降级为空，不能让它拖垮整个列表。 */
    private Map<String, Object> eventData(JdbcAuditQueryRepository.RequestEvent event) {
        if (event == null || event.eventData() == null || event.eventData().isBlank()) {
            return Map.of();
        }
        try {
            Object parsed = objectMapper.readValue(event.eventData(), Object.class);
            if (parsed instanceof Map<?, ?> map) {
                Map<String, Object> result = new LinkedHashMap<>();
                map.forEach((key, value) -> result.put(String.valueOf(key), value));
                return result;
            }
        }
        catch (RuntimeException ignored) {
            // 事件数据损坏时列表仍应可用
        }
        return Map.of();
    }

    private String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private Integer number(Object value) {
        return value instanceof Number number ? number.intValue() : null;
    }
}
