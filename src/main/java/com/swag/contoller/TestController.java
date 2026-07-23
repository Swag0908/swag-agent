package com.swag.contoller;

import com.swag.tool.SelectModelTool;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("test")
public class TestController {
    @Autowired
    private SelectModelTool selectModelTool;

    /**
     * 测试聊天接口
     * @param model
     * @param userInput
     * @return
     */
    @GetMapping("/chat")
    public String chat(@RequestParam(value = "model",defaultValue = "1") Integer model,@RequestParam(value = "userInput") String userInput) {
        ChatClient chatClient = selectModelTool.selectModel(model);
        return chatClient.prompt().user(userInput).call().content();
    }

}
