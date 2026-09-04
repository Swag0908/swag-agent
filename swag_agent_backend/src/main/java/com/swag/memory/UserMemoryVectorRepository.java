package com.swag.memory;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 用户级记忆的向量副本（pgvector，与 MySQL 本体按 memory_id 关联）。
 * 供跨会话语义召回 top-k 使用；若 PG/Ollama 不可用，服务层会自动降级为「最近 N 条」。
 * <p>
 * 注意：PG 连接在本类内部自建，**不得**把 PG DataSource 注册为 Spring Bean，
 * 否则会破坏主 MySQL 数据源的自动配置（详见 PgVectorDataSourceConfiguration 注释）。
 */
@Repository
public class UserMemoryVectorRepository {

    private static final Logger log = LoggerFactory.getLogger(UserMemoryVectorRepository.class);

    private final JdbcTemplate pg;

    public UserMemoryVectorRepository(
            @Value("${app.pgvector.datasource.url}") String url,
            @Value("${app.pgvector.datasource.username}") String username,
            @Value("${app.pgvector.datasource.password}") String password) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.postgresql.Driver");
        dataSource.setUrl(url);
        dataSource.setUsername(username);
        dataSource.setPassword(password);
        this.pg = new JdbcTemplate(dataSource);
    }

    @PostConstruct
    public void ensureSchema() {
        try {
            pg.execute("""
                    CREATE TABLE IF NOT EXISTS chat_user_memory_vec (
                        memory_id BIGINT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector(768) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """);
            log.info("chat_user_memory_vec 表结构已就绪");
        }
        catch (Exception e) {
            log.warn("chat_user_memory_vec 建表失败（将回退为最近记忆注入）：{}", e.getMessage());
        }
    }

    public void save(Long memoryId, Long userId, String content, float[] embedding) {
        pg.update("""
                        INSERT INTO chat_user_memory_vec (memory_id, user_id, content, embedding)
                        VALUES (?, ?, ?, ?::vector)
                        ON CONFLICT (memory_id) DO UPDATE
                            SET content = EXCLUDED.content,
                                embedding = EXCLUDED.embedding,
                                user_id = EXCLUDED.user_id
                        """,
                memoryId, userId, content, toPgVector(embedding));
    }

    public void delete(Long memoryId) {
        pg.update("DELETE FROM chat_user_memory_vec WHERE memory_id = ?", memoryId);
    }

    /** 按余弦相似度召回该用户最相关的 topK 条记忆文本。 */
    public List<String> search(Long userId, float[] queryEmbedding, int topK) {
        return pg.queryForList(
                "SELECT content FROM chat_user_memory_vec"
                        + " WHERE user_id = ? ORDER BY embedding <=> ?::vector LIMIT ?",
                String.class,
                userId, toPgVector(queryEmbedding), topK);
    }

    /** float[] → PG vector 文本，如 "[0.1,0.2,...]" */
    private String toPgVector(float[] vector) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vector.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(Float.toString(vector[i]));
        }
        return sb.append(']').toString();
    }
}
