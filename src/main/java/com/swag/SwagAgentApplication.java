package com.swag;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class SwagAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(SwagAgentApplication.class, args);
    }

}
