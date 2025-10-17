import { app } from "../../scripts/app.js";

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

async function getUserApiKey(userId) {
    try {
        const response = await fetch(`/bagel/api_key/${userId}`);
        if (response.ok) {
            const data = await response.json();
            return data.api_key || "";
        }
    } catch (error) {
        console.log("[Bagel] Could not fetch API key:", error);
    }
    return "";
}

app.registerExtension({
    name: "Bagel.AutoFill",
    async nodeCreated(node) {
        const bagelNodeTypes = [
            "BagelImageNode",
            "BagelParisNode",
            "BagelVideoNode",
            "BagelWanVideoNode",
            "BagelVeo3Node",
            "BagelSeeDanceNode"
        ];

        if (bagelNodeTypes.includes(node.comfyClass)) {
            const comfyUser = getCookie("Comfy-User");

            if (comfyUser && comfyUser !== "dev-mode-anonymous" && comfyUser !== "system") {
                const userIdWidget = node.widgets?.find(w => w.name === "user_id");
                if (userIdWidget) {
                    userIdWidget.value = comfyUser;
                }

                const apiKeyWidget = node.widgets?.find(w => w.name === "api_key");
                if (apiKeyWidget) {
                    const apiKey = await getUserApiKey(comfyUser);
                    if (apiKey) {
                        apiKeyWidget.value = apiKey;
                    }
                }
            }
        }
    }
});
