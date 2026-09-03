package com.swag.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 用户长期记忆服务（ChatGPT Memory 式）。
 * <p>
 * 本体存 MySQL（可管理/删除/开关），向量副本存 pgvector。
 * 跨会话注入按提问语义召回 top-k；向量链路（Ollama/PG）异常时降级为最近 N 条文本，
 * 保证记忆功能不会因嵌入服务不可用而整体失效。
 */
@Service
public class UserMemoryService {

    private static final Logger log = LoggerFactory.getLogger(UserMemoryService.class);

    private static final int DEFAULT_TOP_K = 5;
    private static final int MAX_CONTENT_LENGTH = 300;

    private final UserMemoryRepository repository;
    private final UserMemoryVectorRepository vectorRepository;
    private final EmbeddingModel embeddingModel;

    public UserMemoryService(UserMemoryRepository repository,
                             UserMemoryVectorRepository vectorRepository,
                             EmbeddingModel embeddingModel) {
        this.repository = repository;
        this.vectorRepository = vectorRepository;
        this.embeddingModel = embeddingModel;
    }

    public List<UserMemoryDO> list(Long userId) {
        return repository.list(userId);
    }

    public boolean isEnabled(Long userId) {
        return repository.isEnabled(userId);
    }

    public void setEnabled(Long userId, boolean enabled) {
        repository.setEnabled(userId, enabled, LocalDateTime.now());
    }

    /** 保存一条精炼事实，并尽量同步写入向量副本（失败仅降级，不影响本体保存）。 */
    public UserMemoryDO remember(Long userId, String rawContent) {
        if (!isEnabled(userId)) {
            throw new IllegalStateException("长期记忆功能当前处于关闭状态，请先在「我的记忆」中开启");
        }
        String content = normalize(rawContent);
        if (content.isEmpty()) {
            throw new IllegalArgumentException("记忆内容不能为空");
        }
        UserMemoryDO memory = repository.insert(userId, content, LocalDateTime.now());
        try {
            float[] embedding = embeddingModel.embed(content);
            vectorRepository.save(memory.getId(), userId, content, embedding);
        }
        catch (Exception e) {
            log.warn("用户 {} 记忆向量化失败（将回退最近记忆注入）：{}", userId, e.getMessage());
        }
        return memory;
    }

    public boolean delete(Long userId, Long memoryId) {
        boolean removed = repository.delete(memoryId, userId);
        if (removed) {
            try {
                vectorRepository.delete(memoryId);
            }
            catch (Exception e) {
                log.warn("删除用户 {} 记忆向量失败：{}", userId, e.getMessage());
            }
        }
        return removed;
    }

    /**
     * 按提问语义召回该用户最相关的记忆文本（默认 topK=5）。
     * 关闭开关或链路异常时返回空/降级最近 N 条，调用方无需感知。
     */
    public List<String> recall(Long userId, String query, int topK) {
        List<String> result = new ArrayList<>();
        if (userId == null || !isEnabled(userId)) {
            return result;
        }
        int k = topK <= 0 ? DEFAULT_TOP_K : topK;
        try {
            float[] queryEmbedding = embeddingModel.embed(query == null ? "" : query);
            result = vectorRepository.search(userId, queryEmbedding, k);
        }
        catch (Exception e) {
            log.warn("用户 {} 记忆向量召回失败，降级最近记忆：{}", userId, e.getMessage());
        }
        if (result.isEmpty()) {
            // 降级：本体内最近 N 条（含向量化失败的记忆），保证功能兜底
            List<UserMemoryDO> recent = repository.list(userId);
            for (int i = 0; i < recent.size() && i < k; i++) {
                result.add(recent.get(i).getContent());
            }
        }
        return result;
    }

    public List<String> recall(Long userId, String query) {
        return recall(userId, query, DEFAULT_TOP_K);
    }

    private String normalize(String raw) {
        if (raw == null) {
            return "";
        }
        String flat = raw.replaceAll("\\s+", " ").trim();
        if (flat.length() <= MAX_CONTENT_LENGTH) {
            return flat;
        }
        return flat.substring(0, MAX_CONTENT_LENGTH) + "…";
    }
}
