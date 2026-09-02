package com.swag.conifg;

import com.swag.audit.advisor.AuditAdvisor;
import com.swag.audit.tool.AuditToolCallbackFactory;
import com.swag.sites.WebsiteTools;
import com.swag.todo.TodoTools;
import com.swag.tool.DateTimeTools;
import com.swag.tool.WebSearchTools;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.ai.chat.client.advisor.vectorstore.VectorStoreChatMemoryAdvisor;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.memory.MessageWindowChatMemory;
import org.springframework.ai.chat.memory.repository.jdbc.JdbcChatMemoryRepository;
import org.springframework.ai.deepseek.DeepSeekChatOptions;
import org.springframework.ai.deepseek.api.DeepSeekApi;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import reactor.core.scheduler.Schedulers;

@Configuration
public class ChatClientConfig {
    @Autowired
    private DateTimeTools dateTimeTools;

    @Autowired
    private AuditAdvisor auditAdvisor;

    @Autowired
    private AuditToolCallbackFactory auditToolCallbackFactory;

    @Autowired
    private TodoTools todoTools;

    @Autowired
    private WebSearchTools webSearchTools;

    @Autowired
    private WebsiteTools websiteTools;

    /** 短期记忆仓库（主 MySQL），由 spring-ai-starter-model-chat-memory-repository-jdbc 自动装配。 */
    @Autowired
    private JdbcChatMemoryRepository jdbcChatMemoryRepository;

    /** 长期语义记忆向量库（pgvector），见 PgVectorDataSourceConfiguration。 */
    @Autowired
    private VectorStore vectorStore;

    /**
     * 短期记忆：每用户最近 {@code maxMessages} 条消息逐字回放（存 MySQL），
     * 保证「上句刚说、这句简短引用」这类对话不会断片。40 条 ≈ 20 轮一问一答。
     */
    @Bean
    public ChatMemory jdbcChatMemory() {
        return MessageWindowChatMemory.builder()
                .chatMemoryRepository(jdbcChatMemoryRepository)
                .maxMessages(40)
                .build();
    }

    /**
     * 长期记忆：把每轮消息向量化写入 pgvector，提问时按语义召回最相关的历史片段。
     * 对话隔离靠每次请求注入的 conversationId（= userId）。
     */
    @Bean
    public VectorStoreChatMemoryAdvisor vectorStoreChatMemoryAdvisor() {
        return VectorStoreChatMemoryAdvisor.builder(vectorStore)
                .defaultTopK(5)
                // 流式下必须同步写/读，否则连发的下一轮可能在上一轮落库完成前启动而读不到记忆
                .scheduler(Schedulers.immediate())
                .build();
    }

    @Bean("deepSeekV4FlashChatClient")
    public ChatClient deepSeekV4FlashChatClient(ChatClient.Builder builder) {
        return builder.clone().defaultOptions(
                    DeepSeekChatOptions.builder().model(DeepSeekApi.ChatModel.DEEPSEEK_V4_FLASH)
                ).defaultAdvisors(auditAdvisor,
                        MessageChatMemoryAdvisor.builder(jdbcChatMemory())
                                // 同上：流式落库同步化，避免相邻两轮竞态丢记忆
                                .scheduler(Schedulers.immediate())
                                .build(),
                        vectorStoreChatMemoryAdvisor())
                .defaultTools((Object[]) auditToolCallbackFactory.wrap(
                        ToolCallbacks.from(dateTimeTools, todoTools, webSearchTools, websiteTools)))
                .build();
    }
}
