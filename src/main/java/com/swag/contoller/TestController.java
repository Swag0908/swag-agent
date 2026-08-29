package com.swag.contoller;

import com.swag.tool.SelectModelTool;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

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

    /**
     * 流式聊天接口：返回纯文本流（逐字输出），前端通过 Vite 代理读取。
     * @param model
     * @param userInput
     * @return
     */
    @GetMapping(value = "/chat/stream", produces = MediaType.TEXT_PLAIN_VALUE)
    public Flux<String> chatStream(@RequestParam(value = "model", defaultValue = "1") Integer model,
                                   @RequestParam(value = "userInput") String userInput) {
        ChatClient chatClient = selectModelTool.selectModel(model);
        return chatClient.prompt().user(userInput).stream().content()
                .onErrorResume(e -> Flux.just("\n\n[错误] " + e.getMessage()));
    }

}
