package com.swag.tool;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

/**
 * 模型选择
 */
@Component
public class SelectModelTool {
    @Autowired
    private ChatClient deepSeekV4FlashChatClient;
    @Autowired
    private ChatClient deepSeekV4ProChatClient;

    public ChatClient selectModel(Integer model) {
       switch (model){
           case 1:
              return deepSeekV4FlashChatClient;
           case 2:
              return deepSeekV4ProChatClient;
           default:
               throw new ResponseStatusException(
                       HttpStatus.BAD_REQUEST, "model must be 1 or 2");
           }
    }
}
