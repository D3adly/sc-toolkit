"""Mr Kraken's Star Citizen one-page infographic guides
(https://mrkraken.space/one-page-guides/ — his own maintained index).

Each RSI Community Hub post's media gallery mixes several kinds of image:
a 16:9 promo/announcement thumbnail (NOT the guide itself — it's a social
preview with a character portrait eating half the frame), the actual dense
one-page infographic(s) at much higher resolution, translated duplicates of
the same page, and sometimes genuinely separate companion maps. Every entry
below was individually opened and visually verified to be real guide
content, not a promo crop — picking by "largest image in the post" alone
was tried first and got this wrong for several guides.

Direct image URLs point at RSI Community Hub-hosted originals. Those URLs
are hash/token-based and not guaranteed permanently stable — if a link
ever 404s, re-check the index page above for the current one.
"""

GUIDES_INDEX_URL = "https://mrkraken.space/one-page-guides/"

# (display title, [(page label, direct image URL), ...], source post URL)
# Most guides are a single page; a few post genuinely separate companion
# images (extra facility maps, route maps) — those appear as pages in the
# Maps view's PAGE selector. Only actual maps/location guides are listed
# (event summaries and finished events were dropped).
GUIDES = [
    (
        "Hathor Laser Guide [4.1.0]",
        [(
            "Guide",
            "https://robertsspaceindustries.com/i/16779c4a31b93811ca38b4091799f43e115e4a72/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ31167uZgKaN62nxm7YsxF8DnaDmPBF8nU1DHqQQUukp5rKe1W2JsZrLGvuTe5DS1feVquYJdQmgRsBsDU9SDWYR1KtP2HunEFJ4e8UVkjGTBc/09ad3c3c-e18c-491f-a400-3dbf432f65f8.png",
        )],
        "https://robertsspaceindustries.com/community-hub/post/hathor-laser-one-page-guide-V4mCVfAgVSXbc",
    ),
    (
        "Medical Guide [4.3.1]",
        [(
            "Guide",
            "https://robertsspaceindustries.com/i/0ab7c545b612673422fa4123b58fc6e6a37c0e65/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9YG42ie27PTy6n7LxcCcAkZLhwSDrpE3TXddFZ8qkFomFnn8b4MAbstR3gPjFm1mtf9i4VeAKtjCPFxErNFCQqwNLRe5UvN35PAyfmfC/b11cdff0-4ca6-43b0-9da8-715503715862.png",
        )],
        "https://robertsspaceindustries.com/community-hub/post/medical-one-page-guide-4-3-1-O9ye31KYDfoK2",
    ),
    (
        "Onyx Companion Guide [4.3.1]",
        [
            (
                "Page 1 – Contracts",
                "https://robertsspaceindustries.com/i/a5b8f29a3181ab3ae6904138fefc4c1f7fa43f40/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115oZfkUR4zRCvUaha1bVRCDMaS4QRfm9PKH1GHfGarPKo32yvrn7FRHzgiPkqMeg5cDmG36d8JyeTbdYag77kJLgsKcRT14Fr2gYgnox9Bk/4227ec2e-e8fb-4c8b-a7ca-c936a2d62035.png",
            ),
            (
                "Page 2 – Facility Mechanics",
                "https://robertsspaceindustries.com/i/9fabdf65a4ec616ab8733a70f9c39839ff06f426/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115oZfkUR4zRCvUaha1bVRCDMaS4QRfm9PKH1GHfGarPKo32yvrn7FUDkw5BpcEtezppvdFtzikNbefUoLmj96nxXwrDdVFEUnuWj4UTggjG/5632780a-29c7-42bc-9524-ee7c07bb7498.png",
            ),
            (
                "Page 3 – Engineering Traversal Map",
                "https://robertsspaceindustries.com/i/1fd2e63143d367cd2938df59bc15b1cb65f35056/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115oZfkUR4zRCvUaha1bVRCDMaS4QRfm9PKH1GHfGarPKo32yvrn7HfXght7kqsA7KfDVAu2QH7WikE26rhy45R4CZ2DkKDV7rDSzS6YyLEz/ac4f4646-2b87-45c1-8cb1-e7ff11bc9150.png",
            ),
            (
                "Page 4 – Research Traversal Map (4-7)",
                "https://robertsspaceindustries.com/i/5280b2f78165a125b5f382c08018bdd01cd6ae22/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115oZfkUR4zRCvUaha1bVRCDMaS4QRfm9PKH1GHfGarPKo32yvrn7HofkjtYdV1xHzUnUzfGN3hkewaK1Q5TR2ZEwgE5tu9BbCbLcyZxo6W2/d66ecc8d-a44a-4891-9ef0-fd7437a98ce5.png",
            ),
            (
                "Page 5 – Research Traversal Map (8-9)",
                "https://robertsspaceindustries.com/i/521a753bf743b440d6f5f3df8fdae632a5194013/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115oZfkUR4zRCvUaha1bVRCDMaS4QRfm9PKH1GHfGarPKo32yvrn7HkjT8LBWYdYKrYuo6VQuTrf8qyH5LdxXc9Nv3ZJaJr1rKApRk9RVTKC/c1abdee1-bf94-4c15-907a-78b59cbf554a.png",
            ),
            (
                "Page 6 – Site-B Traversal Map",
                "https://robertsspaceindustries.com/i/22f96847a5f728e63486b82b41e81558f17c33be/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115nizNh7zZWtRr2ddH6v9CynfZimyy64gKotoJRTWchP81eov16UW9Tpwb2nc8TyHvDxiWi4RJxgdpeFoU5iD9eeNbLk39Q42LPGQbGuAaS/7b4d623e-78e7-4e07-823b-3fd9022857ac.png",
            ),
        ],
        "https://robertsspaceindustries.com/community-hub/post/onyx-companion-guide-4-3-1-hyperion-update-U79TAqypFlx6n",
    ),
    (
        "Rock Breaker Companion Guide [4.7 RC]",
        [
            (
                "Main Guide – Rock Cracker Activation",
                "https://robertsspaceindustries.com/i/9bda58cbcb51ce04e73396686a0133568bd9deeb/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9RZtdhLqpQj9isyHWxEMuMgJbHDqaVXdMQU2uyWWQhAXz9NZeiTJGaQq1r9GsCnrVYfScSgj5KwKQfr1PM8FszPnj8sMoKsRJVo8scEA/0f4bccfa-5e08-4508-89ab-8cbf03e6487d.png",
            ),
            (
                "General Missions",
                "https://robertsspaceindustries.com/i/e0b3523376d7456e244fc1c064c0df83ee64167b/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9RZtdhLqpQj9isyHWxEMuMgJbHDqaVXdMQU2uyWWQhAXz9NZekvpXPQ9Y3ceicFXknAnSYRram15Be8uJNKZ9FRtimHpgUfcJojqukNz/b3cf9ca2-34de-4eb6-820f-346f4a10ecbe.png",
            ),
            (
                "Map – Landing / Core / Sector 2",
                "https://robertsspaceindustries.com/i/b1f40fb781988b30ea865210d1fffca745191c61/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9RZtdhLqpQj9isyHWxEMuMgJbHDqaVXdMQU2uyWWQhAXz9NZem5Ts3cKQm7endaDTs1xzhR8JSEbwjF547kWm9QMhzAySVHaMK7uUgYn/e39e15ff-3911-43a8-abaa-4a4f461c7e18.png",
            ),
            (
                "Map – Sector 1",
                "https://robertsspaceindustries.com/i/7ea5dfd73c5c8c789f2aebe0fe1d418281ade049/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9RZtdhLqpQj9isyHWxEMuMgJbHDqaVXdMQU2uyWWQhAXz9NZekt1JFUtLtM8icXrqEjccUs4eXFW6vQ9bGn4DDAcm1RvA9vYzWhL5osC/a9e97303-84d4-43ae-bbe1-d59c40c2fb6b.png",
            ),
            (
                "Map – Laser / Warehouse / Ring",
                "https://robertsspaceindustries.com/i/ca97d962a7e991e50f276135f9be026918d0cd75/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115o9RZtdhLqpQj9isyHWxEMuMgJbHDqaVXdMQU2uyWWQhAXz9NZeibwqhZBUufFy3X9DcG1odwzaHXQ7zgGAboEP4MMT1tN71sWLGqoPa1t/3feff3b0-9faa-44e7-b56c-2c85a4ac1d3d.png",
            ),
        ],
        "https://robertsspaceindustries.com/community-hub/post/rock-breaker-companion-guide-4-7-rc-YmVz8SnzJ7rOe",
    ),
    (
        "Storm Breaker Guide",
        [
            (
                "Main Guide",
                "https://robertsspaceindustries.com/i/d5b75cae73d4652370f91fb54dde3a0099dc4052/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115nHtrspPpXx91aNjdMMA8tSJj8x5z5bDqEocgoE2nuDU3PzpX7Kk5VvKtgcywbyrSA9PA4KfS1o5sxCDGrGEYCdwVYJRgzsxdq6aNquEGn/d0b080de-25e8-4e6c-a064-4bc88ed93d81.png",
            ),
            (
                "Lazarus Complex Map",
                "https://robertsspaceindustries.com/i/153758f754d8c14d590492e8237152c69668a08d/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115mrya4Ag4pwm5NAxvjpXATkM3rfbiuSUb6TuMSzhpXVnNVBGK4EHxcyLYVRNcJTQjf6fJRzE6mC5NtRqfPLWgNfpGv8KtkzTCWw273CTNe/0b85fc4f-0cdd-4fb4-8285-cc2cd1096bf6.png",
            ),
            (
                "Farro Data Center Map",
                "https://robertsspaceindustries.com/i/5535e37c032feef47fd445f286c69055f7d34186/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115mrya4Ag4pwm5NAxvjpXATkM3rfbiuSUb6TuMSzhpXVnNVBGK4ELY1GgJW3L1gZu4U3s5TPzJDXDpDRLAUx8FeR32cFS5y1yBV4N4bnk3Y/d8497a73-25b7-49af-9112-88d985d91ab6.png",
            ),
        ],
        "https://robertsspaceindustries.com/community-hub/post/storm-breaker-one-page-guide-XTU7HaiJkZyFs",
    ),
    (
        "Tactical Strike Groups [4.8]",
        [(
            "Guide",
            "https://robertsspaceindustries.com/i/5b0e5c46e11a5320da3c692cd8e104f19de4e07f/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115mWxyVVN3FT2rhefNjxGZwE5A2qnupHRGBy4HASCGrSiALQ6BkvM8zE3rZCzwkjwijjmjjHQm6W1e9xaTaehYNWp1DnXhUPUVoMPCgiofU/9bca69b0-cda4-41c0-90ae-729a64e0894b.png",
        )],
        "https://robertsspaceindustries.com/community-hub/post/tactical-strike-groups-one-page-guide-4-8-sjPWmXraaPQbH",
    ),
    (
        "Tactical Strike Groups – Trench Runner Map",
        [(
            "Guide",
            "https://robertsspaceindustries.com/i/32c31408af3d6d7fd556fd6a22a02f5d717a9dce/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ3115m6XartThe5Zpk7HkGCSw68nNDcDVsCts5tsRk3XEbfGzTNJemkkd8QrCoTTkTvMJZ8KF7Rj7oCrf6sP1D4hDbgX2MfkgnLqS5FkoBTwRp/eb574fa1-4a66-4858-be17-8c01c71f5b11.png",
        )],
        "https://robertsspaceindustries.com/community-hub/post/tactical-strike-groups-trench-runner-map-4-8-ptu-aEUYl6SZzWZhc",
    ),
    (
        "Vanduul-Tech Smugglers [4.4.0]",
        [(
            "Guide",
            "https://robertsspaceindustries.com/i/bd9f2634a682741d3a7b4fd1d3359b415a2a9436/JLypLpqVPBaNxs8FRN3D3vuTrjntZTaECi8ToQLLZiEgiUjcwEzuY511JgyJBk2nwU4KBWPC3t64FJzEsV4pZ31168KuKAii49FKLbe1eSi1LSLaTzW7zjrqMswGNtxJGTRtwm7WWN7xGKCABhqv16qgZdsESj9i1k8zA6twuyiZE22UPJxykDeaJdR58VzfJn/9d9520e0-0e7d-444e-8cf8-88747189bcd9.png",
        )],
        "https://robertsspaceindustries.com/community-hub/post/vanduul-tech-smugglers-one-page-guide-4-4-0-wegEjvpy1Bcl7",
    ),
]
