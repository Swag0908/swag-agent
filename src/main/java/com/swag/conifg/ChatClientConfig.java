package com.swag.conifg;

import com.swag.tool.DateTimeTools;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.deepseek.DeepSeekChatOptions;
import org.springframework.ai.deepseek.api.DeepSeekApi;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ChatClientConfig {
    @Autowired
    private DateTimeTools dateTimeTools;

    @Bean("deepSeekV4ProChatClient")
    public ChatClient deepSeekV4ProChatClient(ChatClient.Builder builder) {
        return builder.clone().defaultOptions(
                    DeepSeekChatOptions.builder().model(DeepSeekApi.ChatModel.DEEPSEEK_V4_PRO)
                ).defaultTools(dateTimeTools)
                .build();
    }
}
