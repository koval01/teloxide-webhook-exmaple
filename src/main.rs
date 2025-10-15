use std::env;

use teloxide::{prelude::*, update_listeners::{webhooks, UpdateListener}};

#[tokio::main]
async fn main() {
    pretty_env_logger::init();
    log::info!("Starting bot...");

    let bot = Bot::from_env();

    let port: u16 = env::var("PORT")
        .unwrap_or_else(|_| "8080".to_string())
        .parse()
        .expect("PORT env variable value is not an integer");

    let addr = ([0, 0, 0, 0], port).into();

    let host = env::var("HOST").expect("HOST env variable is not set");
    let url = format!("https://{host}/webhook").parse().unwrap();
    log::info!("URL: {url}");

    let (
        mut listener, stop_flag, router
    ) = webhooks::axum_to_router(bot.clone(), webhooks::Options::new(addr, url))
        .await
        .expect("Couldn't set up webhook");

    let app = router.route("/health", axum::routing::get(health_handler));

    let stop_token = listener.stop_token();

    tokio::spawn(async move {
        let tcp_listener = tokio::net::TcpListener::bind(addr)
            .await
            .inspect_err(|_| stop_token.stop())
            .expect("Couldn't bind to the address");
        axum::serve(tcp_listener, app)
            .with_graceful_shutdown(stop_flag)
            .await
            .inspect_err(|_| stop_token.stop())
            .expect("Axum server error");
    });

    teloxide::repl_with_listener(
        bot,
        |bot: Bot, msg: Message| async move {
            bot.send_message(msg.chat.id, "pong").await?;
            Ok(())
        },
        listener,
    )
        .await;
}

async fn health_handler() -> &'static str {
    "OK"
}
