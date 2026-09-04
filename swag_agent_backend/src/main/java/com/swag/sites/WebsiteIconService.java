package com.swag.sites;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.io.InputStream;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 发现并保存书签图标。图标只在首次读取时从站点拉取；之后始终返回数据库中的副本，
 * 这样页面不会依赖第三方图标代理或站点的跨域策略。
 */
@Service
public class WebsiteIconService {

    private static final int MAX_ICON_BYTES = 512 * 1024;
    private static final int MAX_PAGE_BYTES = 256 * 1024;
    private static final Pattern LINK_TAG = Pattern.compile("<link\\b[^>]*>", Pattern.CASE_INSENSITIVE);
    private static final Pattern REL = Pattern.compile("\\brel\\s*=\\s*(['\"])(.*?)\\1", Pattern.CASE_INSENSITIVE);
    private static final Pattern HREF = Pattern.compile("\\bhref\\s*=\\s*(['\"])(.*?)\\1", Pattern.CASE_INSENSITIVE);

    private final WebsiteRepository repository;
    private final HttpClient httpClient;

    // 必须保持"只有一个构造器"：Spring 仅在恰好一个构造器时才会隐式自动装配；
    // 若有多个构造器且都未标 @Autowired，Spring 会回退去找无参构造器，
    // 找不到即抛 No default constructor found（启动失败）。如需为测试注入自定义
    // HttpClient，请给本构造器加 @Autowired 而不是新增第二个构造器。
    public WebsiteIconService(WebsiteRepository repository) {
        this.repository = repository;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    /** Returns an owned cached icon, discovering it once when no cache exists. */
    public Optional<WebsiteRepository.CachedIcon> iconFor(Long userId, Long bookmarkId) {
        WebsiteBookmarkDO bookmark = ownedBookmark(userId, bookmarkId);
        Optional<WebsiteRepository.CachedIcon> cached = repository.findCachedIcon(bookmarkId, userId);
        if (cached.isPresent()) {
            return cached;
        }

        Optional<WebsiteRepository.CachedIcon> discovered = discover(bookmark);
        discovered.ifPresent(icon -> repository.storeCachedIcon(
                bookmarkId, userId, icon.data(), icon.contentType(), LocalDateTime.now(WebsiteService.ZONE)));
        return discovered;
    }

    private WebsiteBookmarkDO ownedBookmark(Long userId, Long bookmarkId) {
        WebsiteBookmarkDO bookmark = repository.findBookmarkById(bookmarkId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "网站不存在：#" + bookmarkId));
        if (!bookmark.getUserId().equals(userId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "网站不存在：#" + bookmarkId);
        }
        return bookmark;
    }

    private Optional<WebsiteRepository.CachedIcon> discover(WebsiteBookmarkDO bookmark) {
        try {
            URI site = URI.create(bookmark.getUrl());
            LinkedHashSet<URI> candidates = new LinkedHashSet<>();
            if (bookmark.getIconUrl() != null && !bookmark.getIconUrl().isBlank()) {
                candidates.add(site.resolve(bookmark.getIconUrl().trim()));
            }
            candidates.addAll(iconsDeclaredBy(site));
            candidates.add(site.resolve("/favicon.ico"));
            candidates.add(site.resolve("/favicon.png"));
            candidates.add(site.resolve("/apple-touch-icon.png"));

            for (URI candidate : candidates) {
                Optional<WebsiteRepository.CachedIcon> icon = downloadImage(candidate);
                if (icon.isPresent()) {
                    return icon;
                }
            }
        }
        catch (IllegalArgumentException ignored) {
            // 书签保存时已校验网址；这里额外容错，图标失败不影响书签本身。
        }
        return Optional.empty();
    }

    private List<URI> iconsDeclaredBy(URI site) {
        Optional<RemoteContent> page = request(site, MAX_PAGE_BYTES, "text/html,application/xhtml+xml");
        if (page.isEmpty() || !page.get().contentType().toLowerCase(Locale.ROOT).contains("html")) {
            return List.of();
        }
        String html = new String(page.get().data(), java.nio.charset.StandardCharsets.UTF_8);
        List<URI> result = new ArrayList<>();
        Matcher links = LINK_TAG.matcher(html);
        while (links.find()) {
            String tag = links.group();
            Matcher rel = REL.matcher(tag);
            Matcher href = HREF.matcher(tag);
            if (!rel.find() || !href.find() || !rel.group(2).toLowerCase(Locale.ROOT).contains("icon")) {
                continue;
            }
            try {
                result.add(site.resolve(href.group(2).trim()));
            }
            catch (IllegalArgumentException ignored) {
                // 单个坏的 <link> 不应阻断其它候选图标。
            }
        }
        return result;
    }

    private Optional<WebsiteRepository.CachedIcon> downloadImage(URI uri) {
        Optional<RemoteContent> response = request(uri, MAX_ICON_BYTES,
                "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8");
        if (response.isEmpty()) {
            return Optional.empty();
        }
        RemoteContent content = response.get();
        String contentType = content.contentType().toLowerCase(Locale.ROOT);
        if (!contentType.startsWith("image/") || content.data().length == 0) {
            return Optional.empty();
        }
        return Optional.of(new WebsiteRepository.CachedIcon(content.data(), content.contentType()));
    }

    /**
     * Rejects private-network targets and redirects before making the request. This keeps a user
     * supplied bookmark from being used as an SSRF tunnel to local services.
     */
    private Optional<RemoteContent> request(URI uri, int maxBytes, String accept) {
        if (!isPublicHttpUri(uri)) {
            return Optional.empty();
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(5))
                    .header("Accept", accept)
                    .header("User-Agent", "SwagAgent-BookmarkIcon/1.0")
                    .GET()
                    .build();
            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream body = response.body()) {
                if (response.statusCode() < 200 || response.statusCode() >= 300) {
                    return Optional.empty();
                }
                byte[] data = body.readNBytes(maxBytes + 1);
                if (data.length > maxBytes) {
                    return Optional.empty();
                }
                String contentType = response.headers().firstValue("Content-Type")
                        .map(value -> value.split(";", 2)[0].trim())
                        .orElse("application/octet-stream");
                return Optional.of(new RemoteContent(data, contentType));
            }
        }
        catch (IOException | InterruptedException ignored) {
            if (ignored instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            return Optional.empty();
        }
    }

    private boolean isPublicHttpUri(URI uri) {
        if (uri == null || uri.getHost() == null
                || !("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))) {
            return false;
        }
        try {
            InetAddress[] addresses = InetAddress.getAllByName(uri.getHost());
            return addresses.length > 0 && java.util.Arrays.stream(addresses).noneMatch(this::isPrivateAddress);
        }
        catch (UnknownHostException ignored) {
            return false;
        }
    }

    private boolean isPrivateAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) {
            return true;
        }
        byte[] raw = address.getAddress();
        return raw.length == 16 && (raw[0] & 0xfe) == 0xfc; // IPv6 unique-local fc00::/7
    }

    private record RemoteContent(byte[] data, String contentType) {
    }
}
