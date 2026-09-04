package com.swag.conifg;

import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.ollama.OllamaEmbeddingModel;
import org.springframework.ai.ollama.api.OllamaApi;
import org.springframework.ai.ollama.api.OllamaEmbeddingOptions;
import org.springframework.ai.vectorstore.pgvector.PgVectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * pgvector 长期语义记忆：应用主数据源仍是 MySQL，这里单独给 PostgreSQL 建向量库连接。
 * <p>
 * 注意：pgvector 的 starter 自动配置会用「主数据源（MySQL）」去建向量库，因此
 * 在 application.properties 里通过 {@code spring.autoconfigure.exclude=...PgVectorStoreAutoConfiguration}
 * 把它关掉，改由本类显式提供 PgVectorStore。
 * <p>
 * 嵌入模型用本地 Ollama（nomic-embed-text，768 维），DeepSeek 不提供 embedding。
 * <p>
 * PG 连接必须在本类内创建（或各仓库内部自建），**不要**把 PG DataSource 注册为 Spring Bean——
 * 否则 Spring Boot 会认为存在自定义 DataSource，不再自动创建主 MySQL 数据源，
 * 导致 Flyway/JDBC 全部指向 PG 而启动失败。
 */
@Configuration
public class PgVectorDataSourceConfiguration {

    /**
     * 显式提供 pgvector 使用的 EmbeddingModel（来自本地 Ollama），
     * 不依赖 Spring AI 按 spring.ai.model.* 的默认装配。
     */
    @Bean
    @Primary
    EmbeddingModel pgVectorEmbeddingModel(
            OllamaApi ollamaApi,
            @Value("${spring.ai.ollama.embedding.model:nomic-embed-text}") String model) {
        return OllamaEmbeddingModel.builder()
                .ollamaApi(ollamaApi)
                .options(OllamaEmbeddingOptions.builder().model(model).build())
                .build();
    }

    @Bean
    PgVectorStore vectorStore(
            @Value("${app.pgvector.datasource.url}") String url,
            @Value("${app.pgvector.datasource.username}") String username,
            @Value("${app.pgvector.datasource.password}") String password,
            EmbeddingModel embeddingModel) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.postgresql.Driver");
        dataSource.setUrl(url);
        dataSource.setUsername(username);
        dataSource.setPassword(password);
        return PgVectorStore.builder(new JdbcTemplate(dataSource), embeddingModel)
                .dimensions(768)
                .indexType(PgVectorStore.PgIndexType.HNSW)
                .initializeSchema(true)
                .build();
    }
}
