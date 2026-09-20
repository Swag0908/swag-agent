package com.swag.conifg;

import com.swag.chat.stream.ToolEventRelay;
import io.micrometer.observation.Observation;
import io.micrometer.observation.ObservationHandler;
import org.springframework.ai.tool.observation.ToolCallingObservationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 把 Spring AI 的工具调用观测接到聊天流上。
 *
 * <p>真实链路里模型的工具调用请求不会出现在 {@code ChatResponse} 流里（Spring AI 的 DeepSeek
 * 实现在 API 层就合并并执行了），所以「正在用哪个工具」只能从这里拿：Spring AI 每执行一个工具
 * 都会开一个 Observation（开始 → 成功/异常），我们监听它转交给 {@link ToolEventRelay}。
 *
 * <p>好处：<b>一个 {@code @Tool} 方法都不用改</b>，也不用替换 Spring AI 自己的
 * {@code ToolCallingManager}；以后新增工具自动拥有状态展示。
 */
@Configuration
public class ToolCallingObservationConfig {

    @Bean
    public ObservationHandler<ToolCallingObservationContext> toolStatusObservationHandler(
            ToolEventRelay relay) {
        return new ObservationHandler<>() {
            @Override
            public boolean supportsContext(Observation.Context context) {
                return context instanceof ToolCallingObservationContext;
            }

            @Override
            public void onStart(ToolCallingObservationContext context) {
                relay.onToolStart(context);
            }

            @Override
            public void onStop(ToolCallingObservationContext context) {
                relay.onToolStop(context, true);
            }

            @Override
            public void onError(ToolCallingObservationContext context) {
                relay.onToolStop(context, false);
            }
        };
    }
}
