package com.swag.conifg;

import com.swag.audit.advisor.AuditAdvisor;
import com.swag.audit.tool.AuditToolCallbackFactory;
    import com.swag.todo.TodoTools;
import com.swag.tool.DateTimeTools;
import com.swag.tool.WebSearchTools;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.deepseek.DeepSeekChatOptions;
import org.springframework.ai.deepseek.api.DeepSeekApi;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

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

    @Bean("deepSeekV4ProChatClient")
    public ChatClient deepSeekV4ProChatClient(ChatClient.Builder builder) {
        return builder.clone().defaultOptions(
                    DeepSeekChatOptions.builder().model(DeepSeekApi.ChatModel.DEEPSEEK_V4_PRO)
                ).defaultAdvisors(auditAdvisor)
                .defaultTools((Object[]) auditToolCallbackFactory.wrap(
                        ToolCallbacks.from(dateTimeTools, todoTools, webSearchTools)))
                .build();
    }
}
