"""Category and tag CRUD, including rename via inline editor."""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from helpers import _url, wait_text, setup_user, cleanup_user


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestCategories:

    def test_create_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        inp = w.until(EC.element_to_be_clickable((By.ID, "category-input")))
        inp.send_keys("My Category" + Keys.RETURN)
        w.until(lambda d: "My Category" in d.find_element(By.ID, "category-list").text)

    def test_rename_category(self, driver, w, ctx):
        ctx["cat_uid"] = driver.execute_script(
            "return document.querySelector('#category-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#category-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#category-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#category-list .ct-name-input');"
            "inp.value='Renamed Category';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        wait_text(driver, w, "Renamed Category")

    def test_create_tag(self, driver, w, ctx):
        inp = w.until(EC.element_to_be_clickable((By.ID, "tag-input")))
        inp.send_keys("My Tag" + Keys.RETURN)
        w.until(lambda d: "My Tag" in d.find_element(By.ID, "tag-list").text)

    def test_rename_tag(self, driver, w, ctx):
        ctx["tag_uid"] = driver.execute_script(
            "return document.querySelector('#tag-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#tag-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        w.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tag-list .ct-name-input")))
        driver.execute_script(
            "var inp=document.querySelector('#tag-list .ct-name-input');"
            "inp.value='Renamed Tag';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        wait_text(driver, w, "Renamed Tag")

    def test_delete_category(self, driver, w, ctx):
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#category-{ctx['cat_uid']} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        w.until(EC.invisibility_of_element_located((By.ID, f"category-{ctx['cat_uid']}")))

    def test_delete_tag(self, driver, w, ctx):
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#tag-{ctx['tag_uid']} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        w.until(EC.invisibility_of_element_located((By.ID, f"tag-{ctx['tag_uid']}")))
