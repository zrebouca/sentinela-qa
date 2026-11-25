package br.sentinela.qa;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.*;

import io.restassured.response.Response;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** Gerado pelo Sentinela QA a partir do roteiro api_viacep.yaml. Rodar: mvn test */
class SentinelaApiTest {

    @Test
    @DisplayName("CT01 - Consultar CEP existente (Praça da Sé, São Paulo)")
    void CT01_Consultar_CEP_existente_Praça_da_Sé_São_Paulo() {
        Response r = null;
        r = given()
            .when().request("GET", "https://viacep.com.br/ws/01001000/json/");
        r.then().statusCode(200);
        r.then().header("content-type", containsStringIgnoringCase("json"));
        r.then().body("cep", hasToString(equalToIgnoringCase(String.valueOf("01001-000"))));
        r.then().body("localidade", hasToString(equalToIgnoringCase(String.valueOf("São Paulo"))));
        r.then().body("uf", hasToString(equalToIgnoringCase(String.valueOf("SP"))));
        r.then().body("logradouro", hasToString(containsString("Praça da Sé")));
        r.then().time(lessThanOrEqualTo(5000L));
    }

    @Test
    @DisplayName("CT02 - CEP com formato inválido (3 dígitos)")
    void CT02_CEP_com_formato_inválido_3_dígitos() {
        Response r = null;
        r = given()
            .when().request("GET", "https://viacep.com.br/ws/123/json/");
        r.then().statusCode(400);
    }

    @Test
    @DisplayName("CT03 - CEP com formato válido mas inexistente")
    void CT03_CEP_com_formato_válido_mas_inexistente() {
        Response r = null;
        r = given()
            .when().request("GET", "https://viacep.com.br/ws/99999999/json/");
        r.then().statusCode(200);
        r.then().body("erro", hasToString(equalToIgnoringCase(String.valueOf("True"))));
        r.then().body("logradouro", nullValue());
    }

    @Test
    @DisplayName("CT04 - Criar post (POST) e consultar um post existente")
    void CT04_Criar_post_POST_e_consultar_um_post_existente() {
        Response r = null;
        r = given()
            .contentType("application/json").body("{\"title\": \"Teste do Sentinela QA\", \"body\": \"{faker.sentence}\", \"userId\": 1}")
            .when().request("POST", "https://jsonplaceholder.typicode.com/posts");
        r.then().statusCode(201);
        r.then().body("id", notNullValue());
        r.then().body("title", hasToString(equalToIgnoringCase(String.valueOf("Teste do Sentinela QA"))));
        String usuario = r.path("userId").toString();
        r = given()
            .when().request("GET", "https://jsonplaceholder.typicode.com/users/" + String.valueOf(usuario));
        r.then().statusCode(allOf(greaterThanOrEqualTo(200), lessThanOrEqualTo(299)));
        r.then().body("address.city", notNullValue());
    }
}
